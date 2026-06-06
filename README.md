# 微信公众号文章转PDF工具

将微信公众号文章转换为精美的PDF文档，保留原文排版和图片。

## 功能特点

- 🔗 **链接抓取**：粘贴微信文章链接，自动获取内容
- 📝 **粘贴文字**：直接粘贴文章内容，一键生成PDF
- 📷 **上传截图**：上传长截图，OCR识别文字
- 🖼️ **保留图片**：自动提取文章中的图片并嵌入PDF
- 📱 **手机适配**：完美支持手机浏览器
- 🔍 **文字可搜索**：PDF支持搜索和复制

## 在线演示

访问：[https://your-app.vercel.app](https://your-app.vercel.app)

## 本地运行

```bash
# 安装依赖
pip install flask reportlab requests Pillow

# 运行服务
python app.py

# 访问 http://localhost:5000
```

## 部署到 Vercel（免费）

### 方法一：一键部署

点击下方按钮，自动部署到 Vercel：

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/your-username/wechat2pdf)

### 方法二：手动部署

```bash
# 1. Fork 本仓库

# 2. 安装 Vercel CLI
npm i -g vercel

# 3. 登录 Vercel
vercel login

# 4. 部署
vercel --prod

# 5. 绑定自定义域名（可选）
vercel domains add your-domain.com
```

## 项目结构

```
├── api/
│   └── index.py          # Vercel Serverless 入口
├── templates/
│   └── index.html        # 前端页面
├── app.py                # 主应用（Flask）
├── vercel.json           # Vercel 配置
├── requirements.txt      # Python 依赖
└── README.md             # 说明文档
```

## 技术栈

- **前端**：HTML5 + CSS3 + JavaScript
- **后端**：Python Flask
- **PDF生成**：ReportLab
- **图片处理**：Pillow
- **部署**：Vercel（免费）

## 许可证

MIT License
