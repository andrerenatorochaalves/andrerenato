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
SOURCE_DIR = Path("blog/_build/html")
OUTPUT_DIR = Path("blog/_build/html_en")
SOURCE_LANG = "pt"
TARGET_LANG = "en"

# Inicializa o tradutor
translator = GoogleTranslator(source=SOURCE_LANG, target=TARGET_LANG)


def should_translate(text):
    """Verifica se o texto deve ser traduzido."""
    # Ignora textos muito curtos ou apenas código
    if len(text. strip()) < 3:
        return False
    # Ignora se for apenas números ou símbolos
    if re.match(r'^[\d\s\.\,\-\+\=\(\)\[\]\{\}\/\*]+$', text):
        return False
    return True


def translate_text(text):
    """Traduz um texto, preservando formatação."""
    if not should_translate(text):
        return text
    
    try:
        # Divide em partes menores se necessário (limite de 5000 chars)
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
                    current_part = sentence + ". "
            
            if current_part:
                parts. append(current_part)
            
            translated_parts = [translator.translate(part) for part in parts]
            return " ".join(translated_parts)
        else:
            return translator.translate(text)
    except Exception as e:
        print(f"Erro ao traduzir:  {e}")
        return text


def translate_html_file(file_path, output_path):
    """Traduz um arquivo HTML preservando as tags."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f. read()
    
    # Padrões para encontrar texto traduzível
    # Traduz conteúdo entre tags, preservando as tags
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
            
            # Não traduz se contiver principalmente código ou HTML
            if '<code' in text or '<pre' in text or '$$' in text or '$' in text:
                return match.group(0)
            
            # Remove tags internas temporariamente
            inner_tags = re.findall(r'<[^>]+>', text)
            text_only = re.sub(r'<[^>]+>', '{{TAG}}', text)
            
            if should_translate(text_only. replace('{{TAG}}', '')):
                translated = translate_text(text_only. replace('{{TAG}}', ''))
                # Restaura tags (simplificado)
                for tag in inner_tags:
                    translated = translated.replace('{{TAG}}', tag, 1)
                groups[group_to_translate - 1] = translated
            
            return ''.join(groups)
        
        translated_content = re. sub(pattern, replace_match, translated_content, flags=re. DOTALL)
    
    # Atualiza o atributo lang
    translated_content = translated_content.replace('lang="pt"', 'lang="en"')
    translated_content = translated_content.replace("lang='pt'", "lang='en'")
    
    # Adiciona link para versão em português
    nav_link = '<a href="../" style="margin-right: 15px;">🇧🇷 Português</a>'
    translated_content = translated_content.replace('</nav>', f'{nav_link}</nav>')
    
    # Salva o arquivo traduzido
    output_path. parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(translated_content)


def main():
    """Função principal."""
    print("Iniciando tradução do blog...")
    
    # Copia toda a estrutura primeiro
    if OUTPUT_DIR.exists():
        shutil. rmtree(OUTPUT_DIR)
    shutil.copytree(SOURCE_DIR, OUTPUT_DIR)
    
    # Traduz arquivos HTML
    html_files = list(OUTPUT_DIR.rglob("*.html"))
    total = len(html_files)
    
    for i, html_file in enumerate(html_files, 1):
        print(f"Traduzindo ({i}/{total}): {html_file. name}")
        translate_html_file(html_file, html_file)
    
    print(f"\nTradução concluída! {total} arquivos processados.")
    print(f"Arquivos salvos em: {OUTPUT_DIR}")


if __name__ == "__main__": 
    main()
