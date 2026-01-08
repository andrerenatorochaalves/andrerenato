"""
Script para traduzir o blog de Português para Inglês automaticamente.  
Usa a biblioteca deep-translator (Google Translate gratuito).
"""

import os
import shutil
import re
from pathlib import Path
from deep_translator import GoogleTranslator

# Configurações
SOURCE_LANG = "pt"
TARGET_LANG = "en"

# Inicializa o tradutor
translator = GoogleTranslator(source=SOURCE_LANG, target=TARGET_LANG)


def find_build_dir():
    """Encontra o diretório de build do Jupyter Book."""
    # Lista toda a estrutura para debug
    print("=== Estrutura de diretórios ===")
    for root, dirs, files in os.walk(". "):
        # Ignora . git e outros diretórios ocultos
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        level = root.replace(".", "").count(os.sep)
        indent = " " * 2 * level
        print(f"{indent}{os.path.basename(root)}/")
        
        # Mostra apenas arquivos HTML para identificar o build
        html_files = [f for f in files if f.endswith('.html')]
        if html_files: 
            subindent = " " * 2 * (level + 1)
            for f in html_files[: 3]: 
                print(f"{subindent}{f}")
            if len(html_files) > 3:
                print(f"{subindent}... e mais {len(html_files) - 3} arquivos HTML")
    
    print("=== Fim da estrutura ===\n")
    
    # Tenta encontrar o diretório de build
    possible_paths = [
        Path("blog/_build/html"),
        Path("_build/html"),
    ]
    
    for path in possible_paths:
        if path.exists() and path.is_dir():
            # Verifica se tem arquivos HTML
            html_files = list(path.glob("*.html"))
            if html_files:
                print(f"✓ Diretório de build encontrado: {path}")
                return path
    
    print("✗ Nenhum diretório de build válido encontrado")
    return None


def should_translate(text):
    """Verifica se o texto deve ser traduzido."""
    if not text or len(text. strip()) < 3:
        return False
    if re.match(r'^[\d\s\.\,\-\+\=\(\)\[\]\{\}\/\*]+$', text):
        return False
    return True


def translate_text(text):
    """Traduz um texto, preservando formatação."""
    if not should_translate(text):
        return text
    
    try:
        if len(text) > 4500:
            parts = []
            sentences = text.split('. ')
            current_part = ""
            
            for sentence in sentences:
                if len(current_part) + len(sentence) < 4500:
                    current_part += sentence + ".  "
                else:
                    if current_part:
                        parts.append(current_part)
                    current_part = sentence + ".  "
            
            if current_part:
                parts.append(current_part)
            
            translated_parts = [translator.translate(part) for part in parts]
            return " ".join(translated_parts)
        else:
            return translator.translate(text)
    except Exception as e:
        print(f"Erro ao traduzir: {e}")
        return text


def translate_html_file(file_path):
    """Traduz um arquivo HTML preservando as tags."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"  Erro ao ler arquivo: {e}")
        return
    
    patterns = [
        (r'(<title>)(.*?)(</title>)', 2),
        (r'(<h[1-6][^>]*>)(.*?)(</h[1-6]>)', 2),
        (r'(<p[^>]*>)(.*?)(</p>)', 2),
        (r'(<li[^>]*>)(.*?)(</li>)', 2),
        (r'(<td[^>]*>)(.*?)(</td>)', 2),
        (r'(<th[^>]*>)(.*?)(</th>)', 2),
        (r'(<figcaption[^>]*>)(.*?)(</figcaption>)', 2),
        (r'(<span class="caption-text">)(.*?)(</span>)', 2),
    ]
    
    translated_content = content
    
    for pattern, group_to_translate in patterns:
        def replace_match(match):
            groups = list(match.groups())
            text = groups[group_to_translate - 1]
            
            if '<code' in text or '<pre' in text or '$$' in text or '$' in text:
                return match.group(0)
            
            inner_tags = re.findall(r'<[^>]+>', text)
            text_only = re.sub(r'<[^>]+>', '{{TAG}}', text)
            
            if should_translate(text_only. replace('{{TAG}}', '')):
                translated = translate_text(text_only.replace('{{TAG}}', ''))
                for tag in inner_tags:
                    translated = translated.replace('{{TAG}}', tag, 1)
                groups[group_to_translate - 1] = translated
            
            return ''.join(groups)
        
        translated_content = re.sub(pattern, replace_match, translated_content, flags=re.DOTALL)
    
    translated_content = translated_content.replace('lang="pt"', 'lang="en"')
    translated_content = translated_content.replace("lang='pt'", "lang='en'")
    
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(translated_content)
    except Exception as e:
        print(f"  Erro ao salvar arquivo: {e}")


def main():
    """Função principal."""
    print("Iniciando tradução do blog.. .\n")
    
    source_dir = find_build_dir()
    
    # Define o diretório de saída
    output_dir = Path("blog/_build/html_en")
    
    if source_dir is None:
        print("\nERRO: Não foi possível encontrar o diretório de build.")
        print("Criando diretório placeholder para não quebrar o deploy...")
        output_dir.mkdir(parents=True, exist_ok=True)
        placeholder = """<!DOCTYPE html>
<html lang="en">
<head><title>Blog - Coming Soon</title></head>
<body>
<h1>English version coming soon</h1>
<p><a href="../">← Versão em Português</a></p>
</body>
</html>"""
        (output_dir / "index.html").write_text(placeholder)
        print(f"Placeholder criado em: {output_dir}")
        return
    
    # Copia toda a estrutura
    print(f"\nCopiando {source_dir} para {output_dir}...")
    if output_dir.exists():
        shutil.rmtree(output_dir)
    shutil.copytree(source_dir, output_dir)
    
    # Traduz arquivos HTML
    html_files = list(output_dir.rglob("*.html"))
    total = len(html_files)
    
    print(f"\nTraduzindo {total} arquivos HTML...")
    for i, html_file in enumerate(html_files, 1):
        print(f"  ({i}/{total}) {html_file.name}")
        translate_html_file(html_file)
    
    print(f"\n✓ Tradução concluída!  {total} arquivos processados.")
    print(f"✓ Arquivos salvos em: {output_dir}")


if __name__ == "__main__":
    main()
