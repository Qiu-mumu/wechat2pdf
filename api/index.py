#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信公众号文章转PDF - Vercel Serverless API
所有代码集中在此文件，适配Vercel平台
"""

import os
import re
import tempfile
import io
import hashlib
from datetime import datetime

from flask import Flask, request, send_file, jsonify, Response

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
    IMAGE_AVAILABLE = True
except ImportError:
    IMAGE_AVAILABLE = False

# 网络请求
import requests as req_lib

# ==================== 初始化 ====================

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024

# Vercel使用 /tmp 作为临时目录
TEMP_DIR = '/tmp/wechat2pdf'
os.makedirs(TEMP_DIR, exist_ok=True)

# ==================== 字体 ====================

def register_cjk_font():
    font_paths = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansSC-Regular.otf",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    ]
    for font_path in font_paths:
        if os.path.exists(font_path):
            try:
                pdfmetrics.registerFont(TTFont("CJKFont", font_path, subfontIndex=0))
                return "CJKFont"
            except:
                continue
    return "Helvetica"

# ==================== 样式 ====================

class ColoredDivider(Flowable):
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

def get_styles(font_name='CJKFont'):
    return {
        'title': ParagraphStyle('Title', fontName=font_name, fontSize=22, leading=30,
            textColor=HexColor('#1a1a1a'), spaceAfter=8, alignment=TA_LEFT, wordWrap='CJK'),
        'author': ParagraphStyle('Author', fontName=font_name, fontSize=11, leading=16,
            textColor=HexColor('#888888'), spaceAfter=20, alignment=TA_LEFT, wordWrap='CJK'),
        'h1': ParagraphStyle('H1', fontName=font_name, fontSize=16, leading=24,
            textColor=HexColor('#1a1a1a'), spaceBefore=20, spaceAfter=10, wordWrap='CJK'),
        'h2': ParagraphStyle('H2', fontName=font_name, fontSize=14, leading=22,
            textColor=HexColor('#333333'), spaceBefore=16, spaceAfter=8, wordWrap='CJK'),
        'body': ParagraphStyle('Body', fontName=font_name, fontSize=12, leading=22,
            textColor=HexColor('#333333'), spaceAfter=12, wordWrap='CJK',
            alignment=TA_JUSTIFY, firstLineIndent=24),
        'quote': ParagraphStyle('Quote', fontName=font_name, fontSize=11, leading=20,
            textColor=HexColor('#666666'), spaceBefore=12, spaceAfter=12, wordWrap='CJK',
            leftIndent=20, rightIndent=20, backColor=HexColor('#f5f5f5'), borderPadding=10),
        'caption': ParagraphStyle('Caption', fontName=font_name, fontSize=9, leading=14,
            textColor=HexColor('#999999'), alignment=TA_CENTER, spaceBefore=6, spaceAfter=16, wordWrap='CJK'),
        'footer': ParagraphStyle('Footer', fontName=font_name, fontSize=9, leading=12,
            textColor=HexColor('#aaaaaa'), alignment=TA_CENTER, spaceBefore=30, wordWrap='CJK'),
    }

# ==================== 文章解析 ====================

def parse_article(text):
    lines = text.strip().split('\n')
    blocks = []
    title = None
    author = None
    start = 0

    if lines:
        if lines[0].startswith('标题：') or lines[0].startswith('标题:'):
            title = lines[0].replace('标题：', '').replace('标题:', '').strip()
            start = 1
        elif lines[0].startswith('《') and lines[0].endswith('》'):
            title = lines[0].strip()
            start = 1
        elif len(lines[0]) < 50 and len(lines) > 1:
            title = lines[0].strip()
            start = 1

    for i in range(start, min(start + 3, len(lines))):
        line = lines[i].strip()
        if line.startswith('作者：') or line.startswith('作者:'):
            author = line.replace('作者：', '').replace('作者:', '').strip()
            start = i + 1
            break

    if not title:
        title = "微信公众号文章"
    blocks.append(('title', title))
    if author:
        blocks.append(('author', author))

    para = []
    for i in range(start, len(lines)):
        line = lines[i].strip()
        if not line:
            if para:
                blocks.append(('paragraph', ' '.join(para)))
                para = []
            continue
        if line.startswith('[IMAGE:') and line.endswith(']'):
            if para:
                blocks.append(('paragraph', ' '.join(para)))
                para = []
            blocks.append(('image', line[7:-1]))
            continue
        if line.startswith('>') or line.startswith('▎'):
            if para:
                blocks.append(('paragraph', ' '.join(para)))
                para = []
            blocks.append(('quote', line.lstrip('>▎│ ')))
            continue
        if len(line) < 30 and not any(c in line for c in '。，！？；：""''（）') and not para:
            blocks.append(('h2', line))
            continue
        para.append(line)
    if para:
        blocks.append(('paragraph', ' '.join(para)))
    return blocks

# ==================== PDF生成 ====================

def create_pdf(blocks, output_path, title=None, images_map=None):
    font_name = register_cjk_font()
    styles = get_styles(font_name)
    doc = SimpleDocTemplate(output_path, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
    story = []
    cw = A4[0] - 4*cm

    for bt, bc in blocks:
        if bt == 'title':
            story.append(Paragraph(bc, styles['title']))
            story.append(ColoredDivider(cw * 0.15, height=3, color=HexColor('#07c160'), space_after=16))
        elif bt == 'author':
            story.append(Paragraph(f"{bc}  {datetime.now().strftime('%Y-%m-%d')}", styles['author']))
        elif bt == 'h2':
            story.append(Paragraph(bc, styles['h2']))
        elif bt == 'paragraph':
            t = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', bc)
            t = re.sub(r'\*(.*?)\*', r'<i>\1</i>', t)
            story.append(Paragraph(t, styles['body']))
        elif bt == 'quote':
            story.append(Paragraph(bc, styles['quote']))
        elif bt == 'image':
            if images_map and bc in images_map:
                ip = images_map[bc]
                if os.path.exists(ip):
                    try:
                        if IMAGE_AVAILABLE:
                            img = PILImage.open(ip)
                            if img.mode != 'RGB':
                                img = img.convert('RGB')
                            ow, oh = img.size
                            if ow > cw:
                                ratio = cw / ow
                                img = img.resize((int(cw), int(oh * ratio)), PILImage.Resampling.LANCZOS)
                            pp = ip + '_p.jpg'
                            img.save(pp, 'JPEG', quality=85)
                            ri = RLImage(pp, width=cw, height=None)
                            ri.drawHeight = cw * ri.imageHeight / ri.imageWidth
                            ri.drawWidth = cw
                            story.append(ri)
                            story.append(Spacer(1, 8))
                        else:
                            story.append(Paragraph("[图片]", styles['caption']))
                    except:
                        story.append(Paragraph("[图片]", styles['caption']))
            else:
                story.append(Paragraph("[图片]", styles['caption']))

    story.append(Spacer(1, 30))
    story.append(ColoredDivider(cw, height=1, color=HexColor('#e0e0e0'), space_after=10))
    story.append(Paragraph(f"本文档由微信公众号文章转PDF工具生成 | {datetime.now().strftime('%Y-%m-%d')}", styles['footer']))
    doc.build(story)
    return output_path

# ==================== 微信文章抓取 ====================

def fetch_wechat_article(url):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Referer': 'https://mp.weixin.qq.com/'
        }
        resp = req_lib.get(url, headers=headers, timeout=15, allow_redirects=True)
        resp.encoding = 'utf-8'
        if resp.status_code != 200:
            return None, []
        html = resp.text

        title = ''
        m = re.search(r'<h1[^>]*class="rich_media_title[^"]*"[^>]*>(.*?)</h1>', html, re.DOTALL)
        if m:
            title = re.sub(r'<[^>]+>', '', m.group(1)).strip()

        author = ''
        m = re.search(r'id="js_name"[^>]*>(.*?)</a>', html, re.DOTALL)
        if m:
            author = re.sub(r'<[^>]+>', '', m.group(1)).strip()

        imgs = []
        for pattern in [r'<img[^>]+data-src=["\']([^"\']+)["\'][^>]*>', r'<img[^>]+src=["\']([^"\']+)["\'][^>]*>']:
            for u in re.findall(pattern, html):
                if u.startswith('http') and 'emoji' not in u and 'icon' not in u:
                    imgs.append(u)
        imgs = list(set(imgs))

        content = ''
        m = re.search(r'<div[^>]*class="rich_media_content[^"]*"[^>]*>(.*?)</div>\s*<script', html, re.DOTALL)
        if not m:
            m = re.search(r'<div[^>]*id="js_content"[^>]*>(.*?)</div>', html, re.DOTALL)
        if m:
            ch = m.group(1)
            ch = re.sub(r'<script[^>]*>.*?</script>', '', ch, flags=re.DOTALL)
            ch = re.sub(r'<style[^>]*>.*?</style>', '', ch, flags=re.DOTALL)
            ch = re.sub(r'<img[^>]+data-src=["\']([^"\']+)["\'][^>]*>', r'[IMAGE:\1]', ch)
            ch = re.sub(r'<img[^>]+src=["\']([^"\']+)["\'][^>]*>', r'[IMAGE:\1]', ch)
            content = re.sub(r'<[^>]+>', '\n', ch)
            content = re.sub(r'\n\s*\n', '\n\n', content).strip()

        if not content:
            return None, []

        article = ''
        if title:
            article += f"标题：{title}\n\n"
        if author:
            article += f"作者：{author}\n\n"
        article += content
        return article, imgs
    except Exception as e:
        print(f"抓取失败: {e}")
        return None, []

def download_image(img_url, temp_dir):
    try:
        resp = req_lib.get(img_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        if resp.status_code != 200:
            return None
        h = hashlib.md5(img_url.encode()).hexdigest()[:8]
        ext = '.jpg'
        ct = resp.headers.get('content-type', '')
        if 'png' in ct: ext = '.png'
        elif 'gif' in ct: ext = '.gif'
        elif 'webp' in ct: ext = '.webp'
        p = os.path.join(temp_dir, f"img_{h}{ext}")
        with open(p, 'wb') as f:
            f.write(resp.content)
        return p
    except:
        return None

# ==================== HTML页面 ====================

HTML_PAGE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>公众号文章转PDF</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;background:linear-gradient(135deg,#667eea,#764ba2);min-height:100vh;padding:20px 15px}
.container{max-width:600px;margin:0 auto}
.header{text-align:center;color:#fff;margin-bottom:30px;padding-top:20px}
.header h1{font-size:28px;margin-bottom:10px}
.header p{font-size:14px;opacity:.9}
.card{background:#fff;border-radius:16px;padding:24px;margin-bottom:20px;box-shadow:0 10px 40px rgba(0,0,0,.1)}
.tabs{display:flex;margin-bottom:24px;background:#f5f5f5;border-radius:12px;padding:4px}
.tab{flex:1;padding:12px;text-align:center;border-radius:10px;font-size:14px;font-weight:500;cursor:pointer;border:none;background:transparent;color:#666;transition:.3s}
.tab.active{background:#fff;color:#667eea;box-shadow:0 2px 8px rgba(0,0,0,.1)}
.tab-content{display:none}.tab-content.active{display:block}
.form-group{margin-bottom:20px}
label{display:block;margin-bottom:8px;font-size:15px;font-weight:500;color:#333}
input[type="text"],textarea{width:100%;padding:14px;border:2px solid #e8e8e8;border-radius:12px;font-size:15px;transition:.3s;font-family:inherit}
input:focus,textarea:focus{outline:none;border-color:#667eea}
textarea{min-height:200px;resize:vertical}
.input-hint{font-size:13px;color:#999;margin-top:6px}
.btn{width:100%;padding:16px;border:none;border-radius:12px;font-size:17px;font-weight:600;cursor:pointer;transition:.3s;font-family:inherit}
.btn-primary{background:linear-gradient(135deg,#667eea,#764ba2);color:#fff}
.btn-primary:hover{transform:translateY(-2px);box-shadow:0 8px 25px rgba(102,126,234,.4)}
.btn-primary:disabled{opacity:.6;cursor:not-allowed;transform:none}
.progress{display:none;margin-top:20px;text-align:center}
.progress.active{display:block}
.spinner{width:40px;height:40px;border:3px solid #f3f3f3;border-top:3px solid #667eea;border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 12px}
@keyframes spin{0%{transform:rotate(0)}100%{transform:rotate(360deg)}}
.progress-text{font-size:15px;color:#666}
.result{display:none;margin-top:20px;padding:20px;background:#f0fff5;border-radius:12px;border:1px solid #07c160}
.result.active{display:block}
.result-icon{font-size:48px;text-align:center;margin-bottom:12px}
.result-text{text-align:center;font-size:16px;color:#333;margin-bottom:16px}
.btn-success{background:#07c160;color:#fff}
.error{display:none;margin-top:20px;padding:16px;background:#fff5f5;border-radius:12px;border:1px solid #ff4d4f;color:#ff4d4f;font-size:14px}
.error.active{display:block}
.warning{display:none;margin-top:16px;padding:16px;background:#fffbe6;border-radius:12px;border:1px solid #ffc53d;color:#666;font-size:14px}
.warning.active{display:block}
.warning-title{font-weight:600;color:#d48806;margin-bottom:8px}
.steps{background:#f8f9fa;border-radius:12px;padding:16px;margin-bottom:20px}
.steps-title{font-size:14px;font-weight:600;color:#333;margin-bottom:12px}
.step{display:flex;align-items:flex-start;gap:10px;margin-bottom:10px;font-size:14px;color:#666}
.step-number{width:22px;height:22px;background:#667eea;color:#fff;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600;flex-shrink:0}
.features{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:20px}
.feature{text-align:center;padding:16px 8px;background:#f8f9fa;border-radius:12px}
.feature-icon{font-size:28px;margin-bottom:8px}
.feature-text{font-size:13px;color:#666}
@media(max-width:480px){.header h1{font-size:24px}.card{padding:20px}.features{grid-template-columns:1fr}.tab{font-size:13px;padding:10px}}
</style>
</head>
<body>
<div class="container">
<div class="header"><h1>📄 公众号文章转PDF</h1><p>将微信文章转换为精美的PDF文档</p></div>
<div class="card">
<div class="tabs">
<button class="tab active" onclick="switchTab('link',this)">🔗 链接抓取</button>
<button class="tab" onclick="switchTab('text',this)">📝 粘贴文字</button>
</div>
<div id="link-tab" class="tab-content active">
<div class="steps"><div class="steps-title">📖 使用步骤</div>
<div class="step"><div class="step-number">1</div><div class="step-text">在微信中打开文章，点击右上角「···」</div></div>
<div class="step"><div class="step-number">2</div><div class="step-text">选择「复制链接」</div></div>
<div class="step"><div class="step-number">3</div><div class="step-text">粘贴到下方，点击生成</div></div></div>
<div class="form-group"><label>文章链接 *</label><input type="text" id="article-link" placeholder="https://mp.weixin.qq.com/s/..."><div class="input-hint">支持 mp.weixin.qq.com 链接</div></div>
</div>
<div id="text-tab" class="tab-content">
<div class="steps"><div class="steps-title">📖 使用步骤</div>
<div class="step"><div class="step-number">1</div><div class="step-text">在微信中打开文章，长按选择「复制」</div></div>
<div class="step"><div class="step-number">2</div><div class="step-text">粘贴到下方输入框</div></div>
<div class="step"><div class="step-number">3</div><div class="step-text">点击生成PDF</div></div></div>
<div class="form-group"><label>文章标题（可选）</label><input type="text" id="title" placeholder="输入文章标题"></div>
<div class="form-group"><label>文章内容 *</label><textarea id="content" placeholder="请粘贴微信公众号文章内容..."></textarea></div>
</div>
<button class="btn btn-primary" id="submit-btn" onclick="generatePDF()">✨ 生成PDF文档</button>
<div class="progress" id="progress"><div class="spinner"></div><div class="progress-text" id="progress-text">正在生成PDF...</div></div>
<div class="result" id="result"><div class="result-icon">✅</div><div class="result-text">PDF生成成功！</div><a id="download-link" class="btn btn-success" style="display:inline-block;text-decoration:none;text-align:center">📥 下载PDF文件</a></div>
<div class="warning" id="warning"><div class="warning-title">⚠️ 链接抓取失败</div><div id="warning-text">微信文章有访问限制，建议复制文章内容粘贴生成。</div><button class="btn" style="background:#f5f5f5;color:#666;margin-top:12px;font-size:15px;padding:12px" onclick="switchTab('text',document.querySelectorAll('.tab')[1])">切换到粘贴文字模式</button></div>
<div class="error" id="error"></div>
</div>
<div class="card"><div class="features"><div class="feature"><div class="feature-icon">📱</div><div class="feature-text">手机直接使用</div></div><div class="feature"><div class="feature-icon">🖼️</div><div class="feature-text">保留文章图片</div></div><div class="feature"><div class="feature-icon">🔍</div><div class="feature-text">文字可搜索</div></div></div></div>
</div>
<script>
function switchTab(tab,el){document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));el.classList.add('active');document.querySelectorAll('.tab-content').forEach(c=>c.classList.remove('active'));document.getElementById(tab+'-tab').classList.add('active');hideAll()}
function hideAll(){['result','error','warning'].forEach(id=>document.getElementById(id).classList.remove('active'))}
function showProgress(t){document.getElementById('progress').classList.add('active');document.getElementById('progress-text').textContent=t;document.getElementById('submit-btn').disabled=true}
function hideProgress(){document.getElementById('progress').classList.remove('active');document.getElementById('submit-btn').disabled=false}
function showResult(url,fn){const r=document.getElementById('result'),l=document.getElementById('download-link');l.href=url;l.download=fn;r.classList.add('active')}
function showError(m){const e=document.getElementById('error');e.textContent=m;e.classList.add('active')}
function showWarning(t,m){const w=document.getElementById('warning');w.querySelector('.warning-title').textContent='⚠️ '+t;document.getElementById('warning-text').textContent=m;w.classList.add('active')}
async function generatePDF(){hideAll();const isLink=document.getElementById('link-tab').classList.contains('active');
if(isLink){const link=document.getElementById('article-link').value.trim();if(!link){showError('请输入文章链接');return}if(!link.includes('mp.weixin.qq.com')){showError('请输入正确的微信公众号文章链接');return}
showProgress('正在抓取文章内容和图片...');try{const r=await fetch('/api/fetch-from-link',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:link})});
if(r.status===403){hideProgress();showWarning('链接抓取失败','微信文章有访问限制，建议复制文章内容粘贴生成。');return}
if(!r.ok){const d=await r.json();throw new Error(d.error||'抓取失败')}
const b=await r.blob();hideProgress();showResult(URL.createObjectURL(b),'article.pdf')}catch(e){hideProgress();showWarning('链接抓取失败','微信文章有访问限制，建议复制文章内容粘贴生成。')}}
else{const content=document.getElementById('content').value.trim();const title=document.getElementById('title').value.trim();if(!content){showError('请输入文章内容');return}
showProgress('正在生成PDF...');try{const r=await fetch('/api/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content,title})});
if(!r.ok)throw new Error('生成失败');const b=await r.blob();hideProgress();showResult(URL.createObjectURL(b),(title||'article')+'.pdf')}catch(e){hideProgress();showError('生成PDF失败: '+e.message)}}}
</script>
</body>
</html>'''

# ==================== 路由 ====================

@app.route('/')
def index():
    return Response(HTML_PAGE, mimetype='text/html')

@app.route('/api/generate', methods=['POST'])
def generate_pdf():
    try:
        data = request.get_json()
        content = data.get('content', '')
        title = data.get('title', '')
        if not content:
            return jsonify({'error': '内容不能为空'}), 400
        blocks = parse_article(content)
        output = os.path.join(TEMP_DIR, f"a_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf")
        create_pdf(blocks, output, title)
        return send_file(output, as_attachment=True, download_name=f"{title or 'article'}.pdf")
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/fetch-from-link', methods=['POST'])
def fetch_from_link():
    try:
        data = request.get_json()
        url = data.get('url', '')
        if not url:
            return jsonify({'error': '链接不能为空'}), 400
        if not url.startswith('https://mp.weixin.qq.com/'):
            return jsonify({'error': '仅支持微信公众号文章链接'}), 400
        article, img_urls = fetch_wechat_article(url)
        if not article:
            return jsonify({'error': '无法抓取文章内容'}), 403
        images_map = {}
        for i, iu in enumerate(img_urls[:20]):
            ip = download_image(iu, TEMP_DIR)
            if ip:
                images_map[iu] = ip
        blocks = parse_article(article)
        title = "article"
        for bt, bc in blocks:
            if bt == 'title':
                title = bc
                break
        output = os.path.join(TEMP_DIR, f"a_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf")
        create_pdf(blocks, output, title, images_map)
        for ip in images_map.values():
            try:
                if os.path.exists(ip): os.remove(ip)
                pp = ip + '_p.jpg'
                if os.path.exists(pp): os.remove(pp)
            except: pass
        return send_file(output, as_attachment=True, download_name=f"{title}.pdf")
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
