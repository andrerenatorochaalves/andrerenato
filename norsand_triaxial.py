from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import pandas as pd


# =============================================================================
# USER INPUTS
# =============================================================================
# Update the values in this section to run a forward NorSand triaxial simulation.
# The defaults below are placeholders and should be replaced with your calibrated
# material parameters and desired initial state.


class CSLMode(str, Enum):
    SEMI_LOG = "semi-log"
    CURVED = "curved"


class DrainageMode(str, Enum):
    DRAINED = "drained"
    UNDRAINED = "undrained"


class StrainMode(str, Enum):
    NATURAL = "natural"
    ENGINEERING = "engineering"


class MiMode(str, Enum):
    DAFALIAS_BISHOP = "dafalias-bishop"
    SYMMETRIC_DAFALIAS = "symmetric-dafalias"


class SofteningMode(str, Enum):
    NONE = "none"
    BOOK = "book"


@dataclass
class NorSandInput:
    # CSL
    csl_mode: CSLMode = CSLMode.SEMI_LOG
    gamma: float = 1.8
    lambda_csl: float = 0.1
    csl_a: float = 1.9
    csl_b: float = 0.08
    csl_c: float = 0.7

    # Strength / dilatancy
    mtc: float = 1.25
    n: float = 0.2
    chi: float = 4.0

    # Hardening
    h0: float = 80.0
    hy: float = 0.0
    hcap: float = 25.0

    # Elasticity
    g0_mpa: float = 80.0
    gexp: float = 0.5
    nu: float = 0.2

    # Initial state
    p0: float = 100.0
    k0: float = 0.5
    psi0: float = -0.05
    ocr: float = 1.0

    # Simulation controls
    drainage: DrainageMode = DrainageMode.UNDRAINED
    strain_mode: StrainMode = StrainMode.ENGINEERING
    max_strain_txl: float = 0.35
    num_points_txl: int = 6000

    # Path controls
    cid_dqdp: float = 3.0
    compute_instability: bool = False
    eta_drain_to_undrain: float = 0.8
    compute_unreload: bool = False
    strain_at_unload: float = 5.0  # percent axial strain, matching VBA output check

    # Options
    mi_mode: MiMode = MiMode.DAFALIAS_BISHOP
    softening_mode: SofteningMode = SofteningMode.NONE
    pore_water_compressible: bool = True

    # Output
    output_dir: str = "outputs"
    history_filename: str = "triax_history.parquet"
    summary_filename: str = "triax_summary.parquet"


INPUTS = NorSandInput()


# =============================================================================
# CONSTANTS
# =============================================================================
ONE_THIRD = 1.0 / 3.0
DEGREE_30 = math.pi / 6.0
DEGREE_90 = math.pi / 2.0
WATER_BULK = 2_000_000.0  # kPa
MPA_TO_KPA = 1000.0
PREF = 100.0
SPACING_RATIO = math.e
E_MIN = 0.2
SIGM_FLOOR = 0.1


# =============================================================================
# DATA STRUCTURES
# =============================================================================
@dataclass
class ModelState:
    step: int
    phase: str
    mode: str
    eps1: float
    epsV: float
    p: float
    q: float
    sig1: float
    sig3: float
    e: float
    psi: float
    eta: float
    Mi: float
    Dp: float
    mi_minus_eta: float
    pimg_over_p: float
    pimx_over_p: float
    Pimg: float
    Gmax: float
    Kmax: float
    Ktot: float
    depGp: float
    depVp: float
    depGe: float
    depVe: float
    depG: float
    depV: float


@dataclass
class SimulationDiagnostics:
    actual_dmin: float
    actual_psi_at_dmin: float | None
    actual_eta_at_dmin: float | None
    eta_il: float | None
    su_il: float | None
    sigm_il: float | None
    psi_il: float | None
    sr_qss: float | None
    switched_to_undrained: bool
    completed_steps: int


@dataclass
class SimulationResult:
    history: pd.DataFrame
    summary: pd.DataFrame


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================
def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def e_crit(sigM: float, cfg: NorSandInput, lode_angle: float = DEGREE_30) -> float:
    sigM = max(sigM, SIGM_FLOOR)
    if cfg.csl_mode == CSLMode.CURVED:
        e_txl = cfg.csl_a - cfg.csl_b * (sigM / PREF) ** cfg.csl_c
    else:
        e_txl = cfg.gamma - cfg.lambda_csl * math.log(sigM)
    return max(e_txl, E_MIN)


def lambda_tangent(sigM: float, cfg: NorSandInput) -> float:
    sigM = max(sigM, SIGM_FLOOR)
    if cfg.csl_mode == CSLMode.CURVED:
        return cfg.csl_b * cfg.csl_c * (sigM / PREF) ** cfg.csl_c
    return cfg.lambda_csl


def g_max(void_ratio: float, sigM: float, cfg: NorSandInput) -> float:
    del void_ratio
    sigM = max(sigM, SIGM_FLOOR)
    g0_kpa = cfg.g0_mpa * MPA_TO_KPA
    return g0_kpa * (sigM / cfg.p0) ** cfg.gexp


def soft_term(Ik: float, lam: float, cfg: NorSandInput, Mi: float, Dp: float, eta: float) -> float:
    omega = max(0.0, 1.0 - cfg.chi * lam / cfg.mtc)
    if Dp > 0.0:
        return -omega * Dp * eta * Ik / Mi
    return 0.0


def h_psi(psi: float, lam: float, cfg: NorSandInput) -> float:
    del lam
    return cfg.h0 - cfg.hy * psi


def m_psi_v5(void_ratio: float, pimg: float, cfg: NorSandInput, lode: float = DEGREE_30) -> float:
    if lode > 0.5235:
        m = cfg.mtc
    elif lode < -0.5235:
        m = cfg.mtc / (1.0 + cfg.mtc / 3.0)
    else:
        mte = cfg.mtc / (1.0 + cfg.mtc / 3.0)
        m = cfg.mtc - (cfg.mtc - mte) * math.cos(1.5 * (lode + DEGREE_30))

    ec_i = e_crit(pimg, cfg, lode)
    psi_i = void_ratio - ec_i
    lam = lambda_tangent(pimg, cfg)

    if lam * cfg.chi / cfg.mtc > 0.2:
        chi_i = 1.2 * cfg.chi
    else:
        chi_i = cfg.chi * cfg.mtc / (cfg.mtc - lam * cfg.chi)

    if psi_i > 0.0:
        if cfg.mi_mode == MiMode.SYMMETRIC_DAFALIAS:
            Mi = m * (1.0 - cfg.n * chi_i * psi_i / cfg.mtc)
        else:
            Mi = m
    else:
        Mi = m * (1.0 + cfg.n * chi_i * psi_i / cfg.mtc)

    return max(Mi, 0.7 * m)


def validate_inputs(cfg: NorSandInput) -> NorSandInput:
    cfg.gexp = clamp(cfg.gexp, 0.0, 1.0)
    cfg.ocr = max(cfg.ocr, 1.0)

    eta_from_k0 = (3.0 - 3.0 * cfg.k0) / (1.0 + 2.0 * cfg.k0)
    Mi0 = max(0.3, cfg.mtc + cfg.n * cfg.chi * cfg.psi0)
    sig1 = 3.0 * cfg.p0 / (1.0 + 2.0 * cfg.k0)
    sig3 = cfg.k0 * sig1
    sigQ = sig1 - sig3
    eta = sigQ / cfg.p0
    pimg_over_p = math.exp(eta / Mi0 - 1.0)
    pmx_over_p = math.exp(-cfg.chi * cfg.psi0 / Mi0)
    ocr_max = pmx_over_p / pimg_over_p
    cfg.ocr = min(cfg.ocr, ocr_max)

    psi_limit = cfg.mtc / (cfg.chi * (1.0 - cfg.n))
    if cfg.psi0 > psi_limit:
        cfg.psi0 = psi_limit

    if cfg.csl_mode == CSLMode.CURVED and cfg.drainage == DrainageMode.UNDRAINED:
        ec = e_crit(cfg.p0, cfg)
        e = cfg.psi0 + ec
        gamma_local = e_crit(0.1, cfg)
        if e > gamma_local:
            cfg.psi0 = gamma_local - ec

    ec = e_crit(cfg.p0, cfg)
    e = cfg.psi0 + ec
    if e < E_MIN:
        cfg.psi0 = E_MIN - ec

    if cfg.compute_instability and cfg.eta_drain_to_undrain <= eta_from_k0:
        raise ValueError("Geostatic eta greater than the chosen undrained transition: fix input.")

    return cfg


def _k_over_g(nu: float) -> float:
    return (2.0 * (1.0 + nu)) / (3.0 * (1.0 - 2.0 * nu))


def _record_state(
    history: list[ModelState],
    step: int,
    phase: str,
    mode: DrainageMode,
    strain_mode: StrainMode,
    eps1_true: float,
    epsV_true: float,
    e0: float,
    sample_ht: float,
    p: float,
    q: float,
    e: float,
    psi: float,
    eta: float,
    Mi: float,
    Dp: float,
    pimg_over_p: float,
    pimx_over_p: float,
    Pimg: float,
    Gmax: float,
    Kmax: float,
    Ktot: float,
    depGp: float,
    depVp: float,
    depGe: float,
    depVe: float,
    depG: float,
    depV: float,
) -> None:
    if strain_mode == StrainMode.ENGINEERING:
        one_over_v0 = 1.0 / (1.0 + e0)
        epsV_out = -(e - e0) * one_over_v0 * 100.0
        eps1_out = (1.0 - sample_ht) * 100.0
    else:
        eps1_out = eps1_true * 100.0
        epsV_out = epsV_true * 100.0

    sig1 = p + 2.0 * q / 3.0
    sig3 = p - q / 3.0

    history.append(
        ModelState(
            step=step,
            phase=phase,
            mode=mode.value,
            eps1=eps1_out,
            epsV=epsV_out,
            p=p,
            q=q,
            sig1=sig1,
            sig3=sig3,
            e=e,
            psi=psi,
            eta=eta,
            Mi=Mi,
            Dp=Dp,
            mi_minus_eta=Mi - eta,
            pimg_over_p=pimg_over_p,
            pimx_over_p=pimx_over_p,
            Pimg=Pimg,
            Gmax=Gmax,
            Kmax=Kmax,
            Ktot=Ktot,
            depGp=depGp,
            depVp=depVp,
            depGe=depGe,
            depVe=depVe,
            depG=depG,
            depV=depV,
        )
    )


def run_triaxial_simulation(cfg: NorSandInput) -> SimulationResult:
    cfg = validate_inputs(cfg)

    history: list[ModelState] = []
    diagnostics = SimulationDiagnostics(
        actual_dmin=cfg.mtc,
        actual_psi_at_dmin=None,
        actual_eta_at_dmin=None,
        eta_il=None,
        su_il=None,
        sigm_il=None,
        psi_il=None,
        sr_qss=None,
        switched_to_undrained=False,
        completed_steps=0,
    )

    mode = cfg.drainage
    bulk_pore_fluid = 0.0 if mode == DrainageMode.DRAINED else WATER_BULK
    if cfg.compute_instability:
        mode = DrainageMode.DRAINED
        bulk_pore_fluid = 0.0

    sig1 = 3.0 * cfg.p0 / (1.0 + 2.0 * cfg.k0)
    sig3 = cfg.k0 * sig1
    sigQ = sig1 - sig3
    sigM = cfg.p0
    eta = sigQ / sigM

    epG = 0.0
    epV = 0.0
    ep1 = 0.0
    psi = cfg.psi0
    current_qmax = sigQ
    reloading = False
    sample_ht = 1.0

    ec = e_crit(sigM, cfg)
    e = cfg.psi0 + ec
    e0 = e

    Gmax = g_max(e, sigM, cfg)
    K_over_G = _k_over_g(cfg.nu)
    Kmax = Gmax * K_over_G
    Ktot = Kmax if (mode == DrainageMode.UNDRAINED and not cfg.pore_water_compressible) else 0.0

    if cfg.k0 < 0.95:
        Mi = m_psi_v5(e, sigM, cfg)
        pimg_over_p = cfg.ocr * math.exp(eta / Mi - 1.0)
        Pimg = pimg_over_p * sigM
        for _ in range(200):
            Pimg_old = Pimg
            Mi = m_psi_v5(e, Pimg, cfg)
            pimg_over_p = cfg.ocr * math.exp(eta / Mi - 1.0)
            Pimg = pimg_over_p * sigM
            if ((Pimg - Pimg_old) ** 2) / max(Pimg, SIGM_FLOOR) < 0.0002:
                break
    else:
        Pimg = sigM / SPACING_RATIO
        Mi = m_psi_v5(e, Pimg, cfg)
        pimg_over_p = cfg.ocr * math.exp(eta / Mi - 1.0)

    Mi_tc = Mi
    Dmin = min(cfg.chi * psi, Mi_tc)
    pimx_over_p = math.exp(-Dmin / Mi_tc)

    if mode == DrainageMode.DRAINED:
        bulk_pore_fluid = 0.0
    else:
        bulk_pore_fluid = WATER_BULK

    if cfg.pore_water_compressible:
        Ktot = bulk_pore_fluid * Kmax / (bulk_pore_fluid + Kmax) if bulk_pore_fluid > 0.0 else 0.0
    else:
        Ktot = Kmax if mode == DrainageMode.UNDRAINED else 0.0

    _record_state(
        history=history,
        step=1,
        phase="initial",
        mode=mode,
        strain_mode=cfg.strain_mode,
        eps1_true=ep1,
        epsV_true=epV,
        e0=e0,
        sample_ht=sample_ht,
        p=sigM,
        q=sigQ,
        e=e,
        psi=psi,
        eta=eta,
        Mi=Mi,
        Dp=Mi - eta,
        pimg_over_p=pimg_over_p,
        pimx_over_p=pimx_over_p,
        Pimg=Pimg,
        Gmax=Gmax,
        Kmax=Kmax,
        Ktot=Ktot,
        depGp=0.0,
        depVp=0.0,
        depGe=0.0,
        depVe=0.0,
        depG=0.0,
        depV=0.0,
    )

    j_plastic = 2
    if cfg.ocr > 1.001:
        if mode == DrainageMode.DRAINED:
            if cfg.cid_dqdp > 30000.0:
                dsigM = 0.0
                eta = Mi * (1.0 + math.log(pimg_over_p))
            else:
                sigM_top = sigM * pimg_over_p * SPACING_RATIO
                sigM_btm = 0.0
                Pimg_local = pimg_over_p * sigM
                for _ in range(10):
                    p_ys = 0.5 * (sigM_top + sigM_btm)
                    dsigM = p_ys - sigM
                    dsigQ = dsigM * cfg.cid_dqdp
                    q_ys = sigQ + dsigQ
                    eta_ys = Mi * (1.0 + math.log(Pimg_local / p_ys))
                    if q_ys > p_ys * eta_ys:
                        sigM_top = p_ys
                    else:
                        sigM_btm = p_ys
                sigM = p_ys
                eta = eta_ys
            pimg_over_p = Pimg / sigM
            Gmax = g_max(e, 0.5 * (cfg.p0 + sigM), cfg)
            Kmax = Gmax * K_over_G
            dsigQ = eta * sigM - sigQ
            sigQ += dsigQ
        else:
            Gmax = g_max(e, sigM, cfg)
            eta_ys = Mi * (1.0 + math.log(pimg_over_p))
            dsigM = 0.0
            dsigQ = (eta_ys - eta) * sigM
            sigQ += dsigQ
            eta = eta_ys

        depVp = 0.0
        depGp = 0.0
        depVe = dsigM / Kmax
        depGe = dsigQ / (3.0 * Gmax)
        depV = depVp + depVe
        epV += depV
        e = e - (1.0 + e) * depV
        depG = depGp + depGe
        dep1 = depG + depV / 3.0
        ep1 += dep1
        sample_ht *= (1.0 - dep1)
        ec = e_crit(sigM, cfg)
        psi = e - ec

        _record_state(
            history=history,
            step=2,
            phase="ocr_elastic",
            mode=mode,
            strain_mode=cfg.strain_mode,
            eps1_true=ep1,
            epsV_true=epV,
            e0=e0,
            sample_ht=sample_ht,
            p=sigM,
            q=sigQ,
            e=e,
            psi=psi,
            eta=eta,
            Mi=Mi,
            Dp=depV / depG if abs(depG) > 1e-20 else float("nan"),
            pimg_over_p=pimg_over_p,
            pimx_over_p=pimx_over_p,
            Pimg=pimg_over_p * sigM,
            Gmax=Gmax,
            Kmax=Kmax,
            Ktot=Ktot,
            depGp=depGp,
            depVp=depVp,
            depGe=depGe,
            depVe=depVe,
            depG=depG,
            depV=depV,
        )
        j_plastic = 3

    depGp_base = cfg.max_strain_txl / max(cfg.num_points_txl - 1, 1)
    last_j = j_plastic - 1

    for j in range(j_plastic, cfg.num_points_txl + 1):
        sigQ_old = sigQ
        sigM_old = sigM

        if cfg.compute_instability and not diagnostics.switched_to_undrained and eta > cfg.eta_drain_to_undrain:
            diagnostics.switched_to_undrained = True
            mode = DrainageMode.UNDRAINED
            bulk_pore_fluid = WATER_BULK

        if cfg.compute_unreload and history[-1].eps1 > cfg.strain_at_unload:
            last_j = j - 1
            break

        Gmax = g_max(e, sigM, cfg)
        Ir = Gmax / cfg.p0
        Kmax = Gmax * K_over_G
        Ik = Ir * K_over_G

        if cfg.pore_water_compressible:
            Ktot = bulk_pore_fluid * Kmax / (bulk_pore_fluid + Kmax) if bulk_pore_fluid > 0.0 else 0.0
        else:
            Ktot = Kmax if mode == DrainageMode.UNDRAINED else 0.0

        ec = e_crit(sigM, cfg)
        psi = e - ec
        lam = lambda_tangent(sigM, cfg)
        Dmin = min(cfg.chi * psi, Mi_tc)

        Mi_old = Mi
        Mi_tc = m_psi_v5(e, sigM * pimg_over_p, cfg)
        Mi = Mi_tc
        dMi_over_Mi = 1.0 - Mi_old / Mi if abs(Mi) > 1e-20 else 0.0

        depGp = depGp_base
        Dp = -Mi * math.log(max(pimg_over_p, 1e-30))
        depVp = Dp * depGp

        dpmx_depGp = 0.0
        if cfg.softening_mode == SofteningMode.BOOK and mode == DrainageMode.UNDRAINED:
            dpmx_depGp = soft_term(Ik / sigM, lam, cfg, Mi, Dp, eta)

        pimx_over_p = math.exp(-Dmin / Mi_tc)
        hard_term = h_psi(psi, lam, cfg) * pimg_over_p ** (-2.0) * (pimx_over_p - pimg_over_p)
        dpimg_over_pimg = (hard_term + dpmx_depGp) * depGp

        if mode == DrainageMode.DRAINED:
            eta_ratio = 1.0 + Mi / (cfg.cid_dqdp - eta)
            deta = (eta * dMi_over_Mi + Mi * dpimg_over_pimg) / eta_ratio
            eta += deta
            dsigM = sigM * deta / (cfg.cid_dqdp - eta)
            dsigQ = sigM * deta + eta * dsigM
            sigM += dsigM
            sigQ = sigM * eta
            pimg_over_p = math.exp(eta / Mi - 1.0)
        else:
            dsigM = -depVp * Ktot
            sigM += dsigM
            if sigM < SIGM_FLOOR:
                sigM = SIGM_FLOOR
                dsigM = sigM - sigM_old
            pimg_over_p = pimg_over_p * (1.0 + dpimg_over_pimg)
            pimg_over_p = pimg_over_p * sigM_old / sigM
            eta = Mi * (1.0 + math.log(max(pimg_over_p, 1e-30)))
            sigQ = sigM * eta
            dsigQ = sigQ - sigQ_old

        depGe = dsigQ / (3.0 * Gmax)
        depVe = dsigM / Kmax
        depV = depVp + depVe
        epV += depV
        depG = depGp + depGe
        dep1 = depG + depV / 3.0
        ep1 += dep1
        e = e - (1.0 + e) * depV
        sample_ht *= (1.0 - dep1)
        Pimg = pimg_over_p * sigM

        if diagnostics.actual_dmin > Dp:
            diagnostics.actual_dmin = Dp
            diagnostics.actual_psi_at_dmin = psi
            diagnostics.actual_eta_at_dmin = eta

        if mode == DrainageMode.UNDRAINED:
            if sigQ > current_qmax:
                if not reloading:
                    current_qmax = sigQ
                    diagnostics.eta_il = eta
                    diagnostics.su_il = sigQ / 2.0
                    diagnostics.sigm_il = sigM
                    diagnostics.psi_il = psi
                    diagnostics.sr_qss = sigQ / 2.0
            else:
                reloading = True
                current_qmax = sigQ
                diagnostics.sr_qss = sigQ / 2.0

        _record_state(
            history=history,
            step=j,
            phase="plastic_loading",
            mode=mode,
            strain_mode=cfg.strain_mode,
            eps1_true=ep1,
            epsV_true=epV,
            e0=e0,
            sample_ht=sample_ht,
            p=sigM,
            q=sigQ,
            e=e,
            psi=psi,
            eta=eta,
            Mi=Mi,
            Dp=Dp,
            pimg_over_p=pimg_over_p,
            pimx_over_p=pimx_over_p,
            Pimg=Pimg,
            Gmax=Gmax,
            Kmax=Kmax,
            Ktot=Ktot,
            depGp=depGp,
            depVp=depVp,
            depGe=depGe,
            depVe=depVe,
            depG=depG,
            depV=depV,
        )
        last_j = j
    else:
        last_j = cfg.num_points_txl

    diagnostics.completed_steps = len(history)

    history_df = pd.DataFrame(asdict(row) for row in history)
    summary_payload: dict[str, Any] = asdict(cfg)
    summary_payload.update(asdict(diagnostics))
    summary_df = pd.DataFrame([summary_payload])

    return SimulationResult(history=history_df, summary=summary_df)


def export_results(result: SimulationResult, cfg: NorSandInput) -> None:
    output_dir = Path(cfg.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    result.history.to_parquet(output_dir / cfg.history_filename, index=False)
    result.summary.to_parquet(output_dir / cfg.summary_filename, index=False)


def main() -> None:
    result = run_triaxial_simulation(INPUTS)
    export_results(result, INPUTS)
    print(f"History written to {Path(INPUTS.output_dir) / INPUTS.history_filename}")
    print(f"Summary written to {Path(INPUTS.output_dir) / INPUTS.summary_filename}")


if __name__ == "__main__":
    main()
