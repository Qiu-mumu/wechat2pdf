#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信公众号文章转PDF工具
支持：1) 粘贴文章文本  2) 上传长截图OCR识别
输出：排版精美的PDF文档
"""

import os
import sys
import re
import argparse
from datetime import datetime

# PDF生成库
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch, cm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.colors import HexColor, white
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, 
    KeepTogether, PageBreak, Flowable
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# OCR库（可选）
try:
    from PIL import Image as PILImage
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False


def register_cjk_font():
    """注册中文字体"""
    system = sys.platform
    font_paths = []
    
    if system == 'win32':
        font_paths = [
            "C:/Windows/Fonts/msyh.ttc",      # 微软雅黑
            "C:/Windows/Fonts/simsun.ttc",    # 宋体
            "C:/Windows/Fonts/simhei.ttf",    # 黑体
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
                print(f"✓ 已加载字体: {os.path.basename(font_path)}")
                return "CJKFont"
            except:
                continue
    
    print("⚠ 警告: 未找到中文字体，PDF可能显示乱码")
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
    """获取专业排版样式（微信风格）"""
    return {
        'title': ParagraphStyle(
            'Title', fontName=font_name, fontSize=22, leading=30,
            textColor=HexColor('#1a1a1a'), spaceAfter=8, 
            alignment=TA_LEFT, wordWrap='CJK',
            spaceBefore=0
        ),
        'author': ParagraphStyle(
            'Author', fontName=font_name, fontSize=11, leading=16,
            textColor=HexColor('#888888'), spaceAfter=20, 
            alignment=TA_LEFT, wordWrap='CJK'
        ),
        'h1': ParagraphStyle(
            'H1', fontName=font_name, fontSize=16, leading=24,
            textColor=HexColor('#1a1a1a'), spaceBefore=20, 
            spaceAfter=10, wordWrap='CJK',
            leftIndent=0
        ),
        'h2': ParagraphStyle(
            'H2', fontName=font_name, fontSize=14, leading=22,
            textColor=HexColor('#333333'), spaceBefore=16, 
            spaceAfter=8, wordWrap='CJK',
            leftIndent=0
        ),
        'body': ParagraphStyle(
            'Body', fontName=font_name, fontSize=12, leading=22,
            textColor=HexColor('#333333'), spaceBefore=0, 
            spaceAfter=12, wordWrap='CJK',
            alignment=TA_JUSTIFY,
            firstLineIndent=24
        ),
        'quote': ParagraphStyle(
            'Quote', fontName=font_name, fontSize=11, leading=20,
            textColor=HexColor('#666666'), spaceBefore=12, 
            spaceAfter=12, wordWrap='CJK',
            leftIndent=20, rightIndent=20,
            backColor=HexColor('#f5f5f5'),
            borderPadding=10
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


def parse_article_text(text):
    """
    解析文章文本，识别标题、作者、段落、引用等
    返回结构化内容列表
    """
    lines = text.strip().split('\n')
    content_blocks = []
    
    # 识别标题（第一行或包含"标题："）
    title = None
    author = None
    start_idx = 0
    
    # 尝试识别标题和作者
    if lines:
        # 检查第一行是否是标题标记
        if lines[0].startswith('标题：') or lines[0].startswith('标题:'):
            title = lines[0].replace('标题：', '').replace('标题:', '').strip()
            start_idx = 1
        elif lines[0].startswith('《') and lines[0].endswith('》'):
            title = lines[0].strip()
            start_idx = 1
        elif len(lines[0]) < 50 and len(lines) > 1:
            # 第一行较短，可能是标题
            title = lines[0].strip()
            start_idx = 1
    
    # 尝试识别作者
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
    
    # 如果没有找到标题，使用默认标题
    if not title:
        title = "微信公众号文章"
    
    content_blocks.append(('title', title))
    if author:
        content_blocks.append(('author', author))
    
    # 解析正文内容
    current_paragraph = []
    in_quote = False
    
    for i in range(start_idx, len(lines)):
        line = lines[i].strip()
        
        if not line:
            # 空行，保存当前段落
            if current_paragraph:
                text = ' '.join(current_paragraph)
                if in_quote:
                    content_blocks.append(('quote', text))
                    in_quote = False
                else:
                    content_blocks.append(('paragraph', text))
                current_paragraph = []
            continue
        
        # 检测引用块（以 > 开头）
        if line.startswith('>') or line.startswith('▎') or line.startswith('│'):
            if current_paragraph and not in_quote:
                text = ' '.join(current_paragraph)
                content_blocks.append(('paragraph', text))
                current_paragraph = []
            in_quote = True
            current_paragraph.append(line.lstrip('>▎│ '))
            continue
        
        # 检测小标题（短行、无标点、前面有空行）
        if (len(line) < 30 and 
            not any(c in line for c in '。，！？；：""''（）') and
            not current_paragraph):
            if current_paragraph:
                text = ' '.join(current_paragraph)
                content_blocks.append(('paragraph', text))
                current_paragraph = []
            content_blocks.append(('h2', line))
            continue
        
        # 检测图片标记
        if line.startswith('![图片]') or line.startswith('[图片]') or line.startswith('【图片】'):
            if current_paragraph:
                text = ' '.join(current_paragraph)
                if in_quote:
                    content_blocks.append(('quote', text))
                    in_quote = False
                else:
                    content_blocks.append(('paragraph', text))
                current_paragraph = []
            content_blocks.append(('image_placeholder', '图片'))
            continue
        
        current_paragraph.append(line)
    
    # 保存最后一个段落
    if current_paragraph:
        text = ' '.join(current_paragraph)
        if in_quote:
            content_blocks.append(('quote', text))
        else:
            content_blocks.append(('paragraph', text))
    
    return content_blocks


def create_pdf(content_blocks, output_path, title=None):
    """
    根据结构化内容生成PDF
    """
    # 注册字体
    font_name = register_cjk_font()
    styles = get_professional_styles(font_name)
    
    # 创建PDF文档
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
    
    # 添加标题
    doc_title = title or "微信公众号文章"
    for block_type, block_content in content_blocks:
        if block_type == 'title':
            doc_title = block_content
            story.append(Paragraph(block_content, styles['title']))
            # 添加装饰线
            story.append(ColoredDivider(content_width * 0.15, height=3, 
                                       color=HexColor('#07c160'), 
                                       space_after=16))
            break
    
    # 添加作者和日期
    author = None
    for block_type, block_content in content_blocks:
        if block_type == 'author':
            author = block_content
            break
    
    if author:
        date_str = datetime.now().strftime("%Y-%m-%d")
        story.append(Paragraph(f"{author}  {date_str}", styles['author']))
    
    # 添加正文内容
    for block_type, block_content in content_blocks:
        if block_type == 'title' or block_type == 'author':
            continue
        
        elif block_type == 'h1':
            story.append(Paragraph(block_content, styles['h1']))
            story.append(ColoredDivider(content_width * 0.1, height=2, 
                                       color=HexColor('#07c160'), 
                                       space_after=10))
        
        elif block_type == 'h2':
            story.append(Paragraph(block_content, styles['h2']))
        
        elif block_type == 'paragraph':
            # 处理粗体和斜体标记
            text = block_content
            text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
            text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
            story.append(Paragraph(text, styles['body']))
        
        elif block_type == 'quote':
            story.append(Paragraph(block_content, styles['quote']))
        
        elif block_type == 'image_placeholder':
            story.append(Paragraph(f"[此处为图片: {block_content}]", styles['caption']))
    
    # 添加页脚
    story.append(Spacer(1, 30))
    story.append(ColoredDivider(content_width, height=1, 
                               color=HexColor('#e0e0e0'), 
                               space_after=10))
    story.append(Paragraph(
        f"本文档由微信公众号文章转PDF工具生成 | {datetime.now().strftime('%Y-%m-%d')}", 
        styles['footer']
    ))
    
    # 构建PDF
    doc.build(story)
    print(f"✓ PDF已生成: {output_path}")
    return output_path


def ocr_image(image_path):
    """
    使用OCR识别图片中的文字
    """
    if not OCR_AVAILABLE:
        print("⚠ OCR功能不可用，请安装依赖: pip install pytesseract pillow")
        print("  同时需要安装Tesseract-OCR引擎")
        return None
    
    try:
        print(f"正在识别图片: {image_path}")
        image = PILImage.open(image_path)
        
        # 使用中文+英文识别
        text = pytesseract.image_to_string(image, lang='chi_sim+eng')
        print(f"✓ OCR识别完成，共 {len(text)} 字符")
        return text
    except Exception as e:
        print(f"✗ OCR识别失败: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description='微信公众号文章转PDF工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 方式1: 从文本文件生成PDF
  python wechat_article_to_pdf.py --input article.txt --output article.pdf
  
  # 方式2: 从长截图OCR识别生成PDF
  python wechat_article_to_pdf.py --image screenshot.png --output article.pdf
  
  # 方式3: 直接输入文本（交互模式）
  python wechat_article_to_pdf.py --interactive
        """
    )
    
    parser.add_argument('--input', '-i', help='输入文本文件路径')
    parser.add_argument('--output', '-o', default='wechat_article.pdf', 
                       help='输出PDF文件路径（默认: wechat_article.pdf）')
    parser.add_argument('--image', '-img', help='输入长截图路径（需要OCR）')
    parser.add_argument('--interactive', '-it', action='store_true',
                       help='交互模式，手动输入文章文本')
    parser.add_argument('--title', '-t', help='文章标题（可选）')
    
    args = parser.parse_args()
    
    print("=" * 50)
    print("微信公众号文章转PDF工具")
    print("=" * 50)
    
    # 获取文章内容
    article_text = None
    
    if args.image:
        # 从图片OCR识别
        print(f"\n模式: 图片OCR识别")
        article_text = ocr_image(args.image)
        if not article_text:
            print("OCR识别失败，请检查图片路径和OCR环境")
            return
    
    elif args.input:
        # 从文件读取
        print(f"\n模式: 文本文件输入")
        if not os.path.exists(args.input):
            print(f"✗ 文件不存在: {args.input}")
            return
        
        with open(args.input, 'r', encoding='utf-8') as f:
            article_text = f.read()
        print(f"✓ 已读取文件: {args.input} ({len(article_text)} 字符)")
    
    elif args.interactive:
        # 交互模式
        print("\n模式: 交互输入")
        print("请粘贴文章内容（输入空行结束）:")
        lines = []
        while True:
            try:
                line = input()
                if not line and lines and not lines[-1]:
                    break
                lines.append(line)
            except EOFError:
                break
        article_text = '\n'.join(lines)
    
    else:
        # 默认交互模式
        print("\n模式: 交互输入")
        print("请粘贴文章内容（按Ctrl+D或Ctrl+Z结束输入）:")
        try:
            article_text = sys.stdin.read()
        except:
            print("✗ 读取输入失败")
            return
    
    if not article_text or not article_text.strip():
        print("✗ 文章内容为空")
        return
    
    # 解析文章
    print("\n正在解析文章结构...")
    content_blocks = parse_article_text(article_text)
    print(f"✓ 解析完成: 共 {len(content_blocks)} 个内容块")
    
    # 生成PDF
    print("\n正在生成PDF...")
    output_path = args.output
    if not output_path.endswith('.pdf'):
        output_path += '.pdf'
    
    create_pdf(content_blocks, output_path, args.title)
    
    print("\n" + "=" * 50)
    print(f"完成！PDF已保存至: {os.path.abspath(output_path)}")
    print("=" * 50)


if __name__ == '__main__':
    main()
