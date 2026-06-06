#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信公众号文章转PDF - 网页版后端服务 V2
支持：链接抓取（含图片）、文字输入、图片OCR
"""

import os
import sys
import re
import tempfile
import requests
import base64
import hashlib
from datetime import datetime
from urllib.parse import urljoin, urlparse
from flask import Flask, request, send_file, render_template, jsonify
from werkzeug.utils import secure_filename

# PDF生成库
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.colors import HexColor
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Flowable, Image as RLImage
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# 图片处理库
try:
    from PIL import Image as PILImage
    from PIL import ImageDraw, ImageFont
    IMAGE_AVAILABLE = True
except ImportError:
    IMAGE_AVAILABLE = False

# OCR库（可选）
try:
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # 32MB max file size

# 创建临时目录
TEMP_DIR = tempfile.mkdtemp()


def register_cjk_font():
    """注册中文字体"""
    system = sys.platform
    font_paths = []
    
    if system == 'win32':
        font_paths = [
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simsun.ttc",
            "C:/Windows/Fonts/simhei.ttf",
        ]
    elif system == 'darwin':
        font_paths = [
            "/System/Library/Fonts/PingFang.ttc",
            "/Library/Fonts/Arial Unicode.ttf",
        ]
    else:
        font_paths = [
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        ]
    
    for font_path in font_paths:
        if os.path.exists(font_path):
            try:
                pdfmetrics.registerFont(TTFont("CJKFont", font_path, subfontIndex=0))
                return "CJKFont"
            except:
                continue
    
    return "Helvetica"


class ColoredDivider(Flowable):
    """彩色分隔线"""
    def __init__(self, width, height=2, color=HexColor('#07c160'), 
                 space_before=6, space_after=12):
        Flowable.__init__(self)
        self.width = width
        self.height = height
        self.color = color
        self.spaceAfter = space_after
        self.spaceBefore = space_before

    def draw(self):
        self.canv.setFillColor(self.color)
        self.canv.rect(0, 0, self.width, self.height, fill=1, stroke=0)


def get_professional_styles(font_name='CJKFont'):
    """获取专业排版样式"""
    return {
        'title': ParagraphStyle(
            'Title', fontName=font_name, fontSize=22, leading=30,
            textColor=HexColor('#1a1a1a'), spaceAfter=8, 
            alignment=TA_LEFT, wordWrap='CJK', spaceBefore=0
        ),
        'author': ParagraphStyle(
            'Author', fontName=font_name, fontSize=11, leading=16,
            textColor=HexColor('#888888'), spaceAfter=20, 
            alignment=TA_LEFT, wordWrap='CJK'
        ),
        'h1': ParagraphStyle(
            'H1', fontName=font_name, fontSize=16, leading=24,
            textColor=HexColor('#1a1a1a'), spaceBefore=20, 
            spaceAfter=10, wordWrap='CJK', leftIndent=0
        ),
        'h2': ParagraphStyle(
            'H2', fontName=font_name, fontSize=14, leading=22,
            textColor=HexColor('#333333'), spaceBefore=16, 
            spaceAfter=8, wordWrap='CJK', leftIndent=0
        ),
        'body': ParagraphStyle(
            'Body', fontName=font_name, fontSize=12, leading=22,
            textColor=HexColor('#333333'), spaceBefore=0, 
            spaceAfter=12, wordWrap='CJK',
            alignment=TA_JUSTIFY, firstLineIndent=24
        ),
        'quote': ParagraphStyle(
            'Quote', fontName=font_name, fontSize=11, leading=20,
            textColor=HexColor('#666666'), spaceBefore=12, 
            spaceAfter=12, wordWrap='CJK',
            leftIndent=20, rightIndent=20,
            backColor=HexColor('#f5f5f5'), borderPadding=10
        ),
        'caption': ParagraphStyle(
            'Caption', fontName=font_name, fontSize=9, leading=14,
            textColor=HexColor('#999999'), alignment=TA_CENTER, 
            spaceBefore=6, spaceAfter=16, wordWrap='CJK'
        ),
        'footer': ParagraphStyle(
            'Footer', fontName=font_name, fontSize=9, leading=12,
            textColor=HexColor('#aaaaaa'), alignment=TA_CENTER, 
            spaceBefore=30, spaceAfter=0, wordWrap='CJK'
        ),
    }


def download_image(img_url, temp_dir, headers=None):
    """下载图片到临时目录"""
    try:
        if not headers:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        
        response = requests.get(img_url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None
        
        # 生成文件名
        url_hash = hashlib.md5(img_url.encode()).hexdigest()[:8]
        ext = '.jpg'
        content_type = response.headers.get('content-type', '')
        if 'png' in content_type:
            ext = '.png'
        elif 'gif' in content_type:
            ext = '.gif'
        elif 'webp' in content_type:
            ext = '.webp'
        
        img_path = os.path.join(temp_dir, f"img_{url_hash}{ext}")
        with open(img_path, 'wb') as f:
            f.write(response.content)
        
        return img_path
    except Exception as e:
        print(f"下载图片失败 {img_url}: {e}")
        return None


def process_image_for_pdf(img_path, max_width=14*cm):
    """处理图片，调整大小适合PDF"""
    try:
        if not IMAGE_AVAILABLE:
            return None
        
        img = PILImage.open(img_path)
        
        # 转换为RGB（处理RGBA、P等模式）
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        
        # 计算缩放比例
        orig_width, orig_height = img.size
        if orig_width > max_width:
            ratio = max_width / orig_width
            new_width = int(max_width)
            new_height = int(orig_height * ratio)
            img = img.resize((new_width, new_height), PILImage.Resampling.LANCZOS)
        
        # 保存处理后的图片
        processed_path = img_path.replace('.', '_processed.')
        if not processed_path.endswith('.jpg'):
            processed_path += '.jpg'
        img.save(processed_path, 'JPEG', quality=85)
        
        return processed_path
    except Exception as e:
        print(f"处理图片失败 {img_path}: {e}")
        return None


def fetch_wechat_article_with_images(url):
    """
    抓取微信文章内容和图片
    返回：(article_text, images_list)
    """
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': 'https://mp.weixin.qq.com/'
        }
        
        response = requests.get(url, headers=headers, timeout=15, allow_redirects=True)
        response.encoding = 'utf-8'
        
        if response.status_code != 200:
            return None, []
        
        html = response.text
        
        # 提取标题
        title_match = re.search(r'<h1[^>]*class="rich_media_title[^"]*"[^>]*>(.*?)</h1>', html, re.DOTALL)
        title = ''
        if title_match:
            title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()
        
        # 提取作者
        author_match = re.search(r'id="js_name"[^>]*>(.*?)</a>', html, re.DOTALL)
        author = ''
        if author_match:
            author = re.sub(r'<[^>]+>', '', author_match.group(1)).strip()
        
        # 提取图片
        images = []
        # 查找所有图片标签
        img_pattern = r'<img[^>]+data-src=["\']([^"\']+)["\'][^>]*>'
        img_matches = re.findall(img_pattern, html)
        
        # 也查找src属性
        img_pattern2 = r'<img[^>]+src=["\']([^"\']+)["\'][^>]*>'
        img_matches2 = re.findall(img_pattern2, html)
        
        all_img_urls = list(set(img_matches + img_matches2))
        
        # 过滤掉非图片URL和太小的图片（表情等）
        for img_url in all_img_urls:
            if not img_url.startswith('http'):
                continue
            if 'emoji' in img_url or 'icon' in img_url:
                continue
            images.append(img_url)
        
        # 提取正文内容（保留图片标记）
        content_match = re.search(r'<div[^>]*class="rich_media_content[^"]*"[^>]*>(.*?)</div>\s*<script', html, re.DOTALL)
        if not content_match:
            content_match = re.search(r'<div[^>]*id="js_content"[^>]*>(.*?)</div>', html, re.DOTALL)
        
        content = ''
        if content_match:
            content_html = content_match.group(1)
            # 清理script和style
            content_html = re.sub(r'<script[^>]*>.*?</script>', '', content_html, flags=re.DOTALL)
            content_html = re.sub(r'<style[^>]*>.*?</style>', '', content_html, flags=re.DOTALL)
            
            # 将图片标签替换为标记
            content_html = re.sub(r'<img[^>]+data-src=["\']([^"\']+)["\'][^>]*>', 
                                r'[IMAGE:\1]', content_html)
            content_html = re.sub(r'<img[^>]+src=["\']([^"\']+)["\'][^>]*>', 
                                r'[IMAGE:\1]', content_html)
            
            # 清理其他HTML标签
            content = re.sub(r'<[^>]+>', '\n', content_html)
            # 清理多余空行
            content = re.sub(r'\n\s*\n', '\n\n', content)
            content = content.strip()
        
        if not content:
            return None, []
        
        # 组合文章
        article = ''
        if title:
            article += f"标题：{title}\n\n"
        if author:
            article += f"作者：{author}\n\n"
        article += content
        
        return article, images
        
    except Exception as e:
        print(f"抓取失败: {e}")
        return None, []


def parse_article_text_with_images(text):
    """
    解析文章文本，识别标题、作者、段落、引用、图片等
    返回结构化内容列表
    """
    lines = text.strip().split('\n')
    content_blocks = []
    
    title = None
    author = None
    start_idx = 0
    
    if lines:
        if lines[0].startswith('标题：') or lines[0].startswith('标题:'):
            title = lines[0].replace('标题：', '').replace('标题:', '').strip()
            start_idx = 1
        elif lines[0].startswith('《') and lines[0].endswith('》'):
            title = lines[0].strip()
            start_idx = 1
        elif len(lines[0]) < 50 and len(lines) > 1:
            title = lines[0].strip()
            start_idx = 1
    
    for i in range(start_idx, min(start_idx + 3, len(lines))):
        line = lines[i].strip()
        if line.startswith('作者：') or line.startswith('作者:'):
            author = line.replace('作者：', '').replace('作者:', '').strip()
            start_idx = i + 1
            break
        elif line.startswith('原创：') or line.startswith('原创:'):
            author = line.replace('原创：', '').replace('原创:', '').strip()
            start_idx = i + 1
            break
    
    if not title:
        title = "微信公众号文章"
    
    content_blocks.append(('title', title))
    if author:
        content_blocks.append(('author', author))
    
    current_paragraph = []
    in_quote = False
    
    for i in range(start_idx, len(lines)):
        line = lines[i].strip()
        
        if not line:
            if current_paragraph:
                text = ' '.join(current_paragraph)
                if in_quote:
                    content_blocks.append(('quote', text))
                    in_quote = False
                else:
                    content_blocks.append(('paragraph', text))
                current_paragraph = []
            continue
        
        # 检测图片标记
        if line.startswith('[IMAGE:') and line.endswith(']'):
            if current_paragraph:
                text = ' '.join(current_paragraph)
                if in_quote:
                    content_blocks.append(('quote', text))
                    in_quote = False
                else:
                    content_blocks.append(('paragraph', text))
                current_paragraph = []
            img_url = line[7:-1]  # 提取URL
            content_blocks.append(('image', img_url))
            continue
        
        # 检测引用块
        if line.startswith('>') or line.startswith('▎') or line.startswith('│'):
            if current_paragraph and not in_quote:
                text = ' '.join(current_paragraph)
                content_blocks.append(('paragraph', text))
                current_paragraph = []
            in_quote = True
            current_paragraph.append(line.lstrip('>▎│ '))
            continue
        
        # 检测小标题
        if (len(line) < 30 and 
            not any(c in line for c in '。，！？；：""''（）') and
            not current_paragraph):
            if current_paragraph:
                text = ' '.join(current_paragraph)
                content_blocks.append(('paragraph', text))
                current_paragraph = []
            content_blocks.append(('h2', line))
            continue
        
        current_paragraph.append(line)
    
    if current_paragraph:
        text = ' '.join(current_paragraph)
        if in_quote:
            content_blocks.append(('quote', text))
        else:
            content_blocks.append(('paragraph', text))
    
    return content_blocks


def create_pdf_with_images(content_blocks, output_path, title=None, images_map=None):
    """
    根据结构化内容生成PDF，支持嵌入图片
    images_map: {url: local_path} 图片URL到本地路径的映射
    """
    font_name = register_cjk_font()
    styles = get_professional_styles(font_name)
    
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=2*cm,
        rightMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm,
    )
    
    story = []
    content_width = A4[0] - 4*cm
    
    doc_title = title or "微信公众号文章"
    for block_type, block_content in content_blocks:
        if block_type == 'title':
            doc_title = block_content
            story.append(Paragraph(block_content, styles['title']))
            story.append(ColoredDivider(content_width * 0.15, height=3, 
                                       color=HexColor('#07c160'), space_after=16))
            break
    
    author = None
    for block_type, block_content in content_blocks:
        if block_type == 'author':
            author = block_content
            break
    
    if author:
        date_str = datetime.now().strftime("%Y-%m-%d")
        story.append(Paragraph(f"{author}  {date_str}", styles['author']))
    
    for block_type, block_content in content_blocks:
        if block_type == 'title' or block_type == 'author':
            continue
        
        elif block_type == 'h1':
            story.append(Paragraph(block_content, styles['h1']))
            story.append(ColoredDivider(content_width * 0.1, height=2, 
                                       color=HexColor('#07c160'), space_after=10))
        
        elif block_type == 'h2':
            story.append(Paragraph(block_content, styles['h2']))
        
        elif block_type == 'paragraph':
            text = block_content
            text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
            text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
            story.append(Paragraph(text, styles['body']))
        
        elif block_type == 'quote':
            story.append(Paragraph(block_content, styles['quote']))
        
        elif block_type == 'image':
            # 嵌入图片
            img_url = block_content
            if images_map and img_url in images_map:
                img_path = images_map[img_url]
                if os.path.exists(img_path):
                    try:
                        # 处理图片大小
                        processed_path = process_image_for_pdf(img_path, max_width=content_width)
                        if processed_path and os.path.exists(processed_path):
                            img = RLImage(processed_path, width=content_width, height=None)
                            # 保持宽高比
                            img_ratio = img.imageHeight / img.imageWidth
                            img.drawHeight = content_width * img_ratio
                            img.drawWidth = content_width
                            story.append(img)
                            story.append(Spacer(1, 8))
                        else:
                            story.append(Paragraph(f"[图片加载失败]", styles['caption']))
                    except Exception as e:
                        print(f"嵌入图片失败: {e}")
                        story.append(Paragraph(f"[图片]", styles['caption']))
                else:
                    story.append(Paragraph(f"[图片]", styles['caption']))
            else:
                story.append(Paragraph(f"[图片]", styles['caption']))
        
        elif block_type == 'image_placeholder':
            story.append(Paragraph(f"[此处为图片: {block_content}]", styles['caption']))
    
    story.append(Spacer(1, 30))
    story.append(ColoredDivider(content_width, height=1, 
                               color=HexColor('#e0e0e0'), space_after=10))
    story.append(Paragraph(
        f"本文档由微信公众号文章转PDF工具生成 | {datetime.now().strftime('%Y-%m-%d')}", 
        styles['footer']
    ))
    
    doc.build(story)
    return output_path


def ocr_image(image_path):
    """OCR识别图片文字"""
    if not OCR_AVAILABLE:
        return None
    
    try:
        image = PILImage.open(image_path)
        text = pytesseract.image_to_string(image, lang='chi_sim+eng')
        return text
    except Exception as e:
        print(f"OCR失败: {e}")
        return None


# ==================== Flask路由 ====================

@app.route('/')
def index():
    """首页"""
    return render_template('index.html')


@app.route('/api/fetch-from-link', methods=['POST'])
def fetch_from_link():
    """从链接抓取文章并生成PDF（含图片）"""
    try:
        data = request.get_json()
        url = data.get('url', '')
        
        if not url:
            return jsonify({'error': '链接不能为空'}), 400
        
        if not url.startswith('https://mp.weixin.qq.com/'):
            return jsonify({'error': '仅支持微信公众号文章链接'}), 400
        
        # 抓取文章内容和图片URL
        article_text, image_urls = fetch_wechat_article_with_images(url)
        
        if not article_text:
            return jsonify({'error': '无法抓取文章内容，微信文章有访问限制'}), 403
        
        # 下载图片
        images_map = {}
        if image_urls:
            print(f"发现 {len(image_urls)} 张图片，开始下载...")
            for i, img_url in enumerate(image_urls[:20]):  # 最多下载20张图片
                img_path = download_image(img_url, TEMP_DIR)
                if img_path:
                    images_map[img_url] = img_path
                    print(f"  ✓ 下载图片 {i+1}/{len(image_urls)}")
                else:
                    print(f"  ✗ 下载图片 {i+1}/{len(image_urls)} 失败")
        
        # 解析文章
        content_blocks = parse_article_text_with_images(article_text)
        
        # 提取标题用于文件名
        title = "article"
        for block_type, block_content in content_blocks:
            if block_type == 'title':
                title = block_content
                break
        
        # 生成PDF
        output_path = os.path.join(TEMP_DIR, f"article_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
        create_pdf_with_images(content_blocks, output_path, title, images_map)
        
        # 清理临时图片文件
        for img_path in images_map.values():
            try:
                if os.path.exists(img_path):
                    os.remove(img_path)
                processed_path = img_path.replace('.', '_processed.')
                if not processed_path.endswith('.jpg'):
                    processed_path += '.jpg'
                if os.path.exists(processed_path):
                    os.remove(processed_path)
            except:
                pass
        
        return send_file(output_path, as_attachment=True, 
                        download_name=f"{title}.pdf")
    
    except Exception as e:
        print(f"处理失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/generate', methods=['POST'])
def generate_pdf():
    """从文字生成PDF"""
    try:
        data = request.get_json()
        content = data.get('content', '')
        title = data.get('title', '')
        
        if not content:
            return jsonify({'error': '内容不能为空'}), 400
        
        # 解析文章
        content_blocks = parse_article_text_with_images(content)
        
        # 生成PDF
        output_path = os.path.join(TEMP_DIR, f"article_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
        create_pdf_with_images(content_blocks, output_path, title)
        
        return send_file(output_path, as_attachment=True, 
                        download_name=f"{title or 'article'}.pdf")
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/generate-from-image', methods=['POST'])
def generate_pdf_from_image():
    """从图片生成PDF"""
    try:
        if 'image' not in request.files:
            return jsonify({'error': '请上传图片'}), 400
        
        file = request.files['image']
        title = request.form.get('title', '')
        
        if file.filename == '':
            return jsonify({'error': '请选择图片文件'}), 400
        
        # 保存上传的图片
        image_path = os.path.join(TEMP_DIR, secure_filename(file.filename))
        file.save(image_path)
        
        # OCR识别
        if not OCR_AVAILABLE:
            return jsonify({'error': 'OCR功能未启用，请安装pytesseract'}), 500
        
        text = ocr_image(image_path)
        if not text:
            return jsonify({'error': '图片识别失败'}), 500
        
        # 解析并生成PDF
        content_blocks = parse_article_text_with_images(text)
        output_path = os.path.join(TEMP_DIR, f"article_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
        create_pdf_with_images(content_blocks, output_path, title)
        
        # 清理临时图片
        os.remove(image_path)
        
        return send_file(output_path, as_attachment=True,
                        download_name=f"{title or 'article'}.pdf")
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    print("=" * 50)
    print("微信公众号文章转PDF - 网页版 V2")
    print("支持图片提取和嵌入")
    print("=" * 50)
    print("请访问: http://localhost:5000")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5000, debug=True)
