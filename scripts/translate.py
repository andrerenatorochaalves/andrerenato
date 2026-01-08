"""
Script para traduzir o blog Quarto de Português para Inglês. 
Traduz arquivos . qmd e células markdown de . ipynb. 
Usa deep-translator (Google Translate gratuito).
"""

import json
import re
from pathlib import Path
from deep_translator import GoogleTranslator

# Configurações
BLOG_DIR = Path("blog")
SOURCE_LANG = "pt"
TARGET_LANG = "en"

translator = GoogleTranslator(source=SOURCE_LANG, target=TARGET_LANG)


def should_translate(text:  str) -> bool:
    """Verifica se o texto deve ser traduzido."""
    if not text or len(text. strip()) < 3:
        return False
    # Ignora texto que é só números/símbolos
    if re.match(r'^[\d\s\.\,\-\+\=\(\)\[\]\{\}\/\*\$\|\: ]+$', text):
        return False
    return True


def translate_text(text: str) -> str:
    """Traduz texto preservando formatação especial."""
    if not should_translate(text):
        return text
    
    # Preservar blocos que não devem ser traduzidos
    preservations = []
    
    def save_block(pattern, text):
        def replacer(match):
            preservations.append(match.group(0))
            return f"__PRESERVE_{len(preservations)-1}__"
        return re.sub(pattern, replacer, text, flags=re. DOTALL)
    
    # Preservar:  código inline, LaTeX, links, imagens
    text = save_block(r'`[^`]+`', text)           # código inline
    text = save_block(r'\$\$[\s\S]+?\$\$', text)  # LaTeX block
    text = save_block(r'\$[^\$]+\$', text)        # LaTeX inline
    text = save_block(r'\[([^\]]+)\]\([^\)]+\)', text)  # links (preserva URL)
    text = save_block(r'!\[([^\]]*)\]\([^\)]+\)', text)  # imagens
    text = save_block(r'```[\s\S]*? ```', text)    # blocos de código
    
    try:
        # Traduzir em chunks se muito grande
        if len(text) > 4500:
            chunks = text.split('\n\n')
            translated_chunks = []
            for chunk in chunks:
                if should_translate(chunk):
                    translated_chunks.append(translator.translate(chunk))
                else: 
                    translated_chunks.append(chunk)
            translated = '\n\n'. join(translated_chunks)
        else:
            translated = translator.translate(text) if should_translate(text) else text
    except Exception as e: 
        print(f"  ⚠ Erro ao traduzir: {e}")
        translated = text
    
    # Restaurar blocos preservados
    for i, block in enumerate(preservations):
        translated = translated.replace(f"__PRESERVE_{i}__", block)
    
    return translated


def translate_qmd(input_path: Path, output_path: Path):
    """Traduz arquivo .qmd preservando YAML front matter e código."""
    content = input_path. read_text(encoding='utf-8')
    
    # Separar YAML front matter
    yaml_match = re. match(r'^(---\n[\s\S]*?\n---\n)', content)
    if yaml_match:
        yaml_part = yaml_match. group(1)
        body = content[len(yaml_part):]
        
        # Traduzir apenas title e subtitle no YAML
        yaml_translated = yaml_part
        for field in ['title', 'subtitle', 'description']:
            pattern = rf'({field}:\s*["\']?)([^"\'\n]+)(["\']?\n)'
            match = re.search(pattern, yaml_translated)
            if match:
                original = match.group(2)
                translated = translate_text(original)
                yaml_translated = yaml_translated.replace(
                    match.group(0), 
                    f'{match.group(1)}{translated}{match.group(3)}'
                )
        
        # Alterar lang para en
        yaml_translated = re.sub(r'lang:\s*pt', 'lang: en', yaml_translated)
    else:
        yaml_translated = ""
        body = content
    
    # Preservar blocos de código no body
    code_blocks = []
    def save_code(match):
        code_blocks.append(match.group(0))
        return f"__CODE_BLOCK_{len(code_blocks)-1}__"
    
    body = re. sub(r'```[\s\S]*? ```', save_code, body)
    
    # Traduzir parágrafos
    paragraphs = body. split('\n\n')
    translated_paragraphs = []
    
    for para in paragraphs: 
        if para.startswith('#') or para.startswith('|') or para.startswith('-'):
            # Headers, tabelas, listas - traduzir com cuidado
            lines = para.split('\n')
            translated_lines = []
            for line in lines:
                if line.startswith('#'):
                    # Header: traduzir apenas o texto após #
                    match = re.match(r'(#+\s*)(.*)', line)
                    if match: 
                        translated_lines.append(f"{match.group(1)}{translate_text(match.group(2))}")
                    else:
                        translated_lines.append(line)
                elif '|' in line and not line.strip().startswith('|--'):
                    # Célula de tabela
                    cells = line.split('|')
                    translated_cells = [translate_text(c) if should_translate(c) else c for c in cells]
                    translated_lines.append('|'.join(translated_cells))
                else:
                    translated_lines.append(translate_text(line) if should_translate(line) else line)
            translated_paragraphs.append('\n'.join(translated_lines))
        else:
            translated_paragraphs. append(translate_text(para))
    
    translated_body = '\n\n'.join(translated_paragraphs)
    
    # Restaurar blocos de código
    for i, block in enumerate(code_blocks):
        translated_body = translated_body.replace(f"__CODE_BLOCK_{i}__", block)
    
    # Salvar
    output_path. parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml_translated + translated_body, encoding='utf-8')


def translate_ipynb(input_path: Path, output_path: Path):
    """Traduz células markdown de um notebook Jupyter."""
    with open(input_path, 'r', encoding='utf-8') as f:
        notebook = json.load(f)
    
    for cell in notebook. get('cells', []):
        if cell.get('cell_type') == 'markdown':
            source = cell.get('source', [])
            if isinstance(source, list):
                text = ''.join(source)
            else:
                text = source
            
            translated = translate_text(text)
            
            # Manter como lista de linhas
            cell['source'] = translated.split('\n')
            cell['source'] = [line + '\n' for line in cell['source'][:-1]] + [cell['source'][-1]]
    
    output_path.parent. mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(notebook, f, ensure_ascii=False, indent=1)


def main():
    """Função principal."""
    print("🌐 Iniciando tradução do blog para inglês.. .\n")
    
    # Criar diretório para versão em inglês
    en_dir = BLOG_DIR / "en"
    en_dir.mkdir(exist_ok=True)
    
    # Copiar _quarto.yml e modificar para inglês
    quarto_config = BLOG_DIR / "_quarto. yml"
    if quarto_config. exists():
        config_content = quarto_config.read_text(encoding='utf-8')
        config_content = config_content.replace('lang: pt', 'lang: en')
        config_content = config_content.replace('/blog', '/blog/en')
        (en_dir / "_quarto.yml").write_text(config_content, encoding='utf-8')
        print("✓ _quarto.yml copiado e adaptado")
    
    # Traduzir arquivos . qmd
    qmd_files = list(BLOG_DIR.rglob("*.qmd"))
    qmd_files = [f for f in qmd_files if "en/" not in str(f) and "_site" not in str(f)]
    
    print(f"\n📄 Traduzindo {len(qmd_files)} arquivos . qmd...")
    for qmd in qmd_files: 
        relative = qmd.relative_to(BLOG_DIR)
        output = en_dir / relative
        print(f"  → {relative}")
        translate_qmd(qmd, output)
    
    # Traduzir notebooks . ipynb
    ipynb_files = list(BLOG_DIR.rglob("*.ipynb"))
    ipynb_files = [f for f in ipynb_files if "en/" not in str(f) and "_site" not in str(f) and ". ipynb_checkpoints" not in str(f)]
    
    print(f"\n📓 Traduzindo {len(ipynb_files)} notebooks...")
    for ipynb in ipynb_files:
        relative = ipynb.relative_to(BLOG_DIR)
        output = en_dir / relative
        print(f"  → {relative}")
        translate_ipynb(ipynb, output)
    
    # Copiar arquivos de metadados
    for meta in BLOG_DIR. rglob("_metadata.yml"):
        if "en/" not in str(meta):
            relative = meta.relative_to(BLOG_DIR)
            output = en_dir / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(meta.read_text(encoding='utf-8'), encoding='utf-8')
    
    print(f"\n✅ Tradução concluída!")
    print(f"   Arquivos salvos em: {en_dir}")


if __name__ == "__main__": 
    main()
