# 考研英语每日阅读 (Kaoyan English Daily)

一个为考研英语备考量身定制的全栈学习平台，集成 AI 驱动的文章生成、阅读理解、完形填空、翻译练习、写作批改和间隔记忆复习。

## 功能

### 核心模块

| 功能 | 说明 |
|------|------|
| **每日文章** | AI 自动生成 350-500 词学术文章，涵盖科技、经济、社会、文化等考研常见话题，附完整中文翻译 |
| **词汇表** | 每篇文章 25-40 个重点词汇，含词性、中文释义、例句，支持一键加入单词本 |
| **翻译练习** | 抽取长难句进行英译中练习，AI 批改并给出评分和详细反馈（1-10 分） |
| **阅读理解** | 仿考研五大题型（主旨大意/事实细节/推理判断/词义猜测/观点态度），每篇 5 题，含详细中文解析 |
| **完形填空** | 10 空完形填空，考察逻辑连接词、固定搭配、近义词辨析、语境理解 |
| **写作练习** | 小作文（应用文）和大作文（图表/图画作文），AI 出题 + 四维度批改（内容/结构/语言/语法） |
| **闪卡复习** | 基于 SM-2 算法的间隔记忆系统，智能调度复习周期 |
| **错题本** | 阅读理解 + 完形填空错题自动汇总，支持标记已复习 |
| **每日打卡** | 学习日历热力图 + 连续天数统计 |
| **暗色模式** | 夜间学习友好 |

### 基础功能

- 点击句子查看中文翻译（按 `T` 一键展开/折叠全部翻译）
- 点击蓝色单词查看弹窗释义（词性、中文、例句、难度等级）
- 文章朗读（浏览器 TTS）
- 学习统计仪表盘
- 文章历史存档
- MySQL / SQLite 双后端支持

## 技术栈

- **后端**: Python / Flask
- **AI**: DeepSeek API（Chat Completions）
- **数据库**: SQLite（默认）/ MySQL（可选）
- **前端**: 原生 JavaScript + CSS，零依赖
- **定时任务**: APScheduler（每日 8:00 自动生成文章）

## 项目结构

```
├── app.py                # Flask 应用入口，所有路由和 API
├── db.py                 # 数据库连接管理（SQLite / MySQL）
├── generator.py          # AI 文章生成 + 验证 + 存储
├── article_store.py      # 文章查询 + 关联数据组装
├── translate_service.py  # 翻译服务（可选）
├── scheduler.py          # 每日 8:00 自动生成定时任务
├── requirements.txt      # Python 依赖
├── .env                  # 环境变量配置
├── IDEA.md               # 项目设计思路
│
├── data/
│   ├── english.db        # SQLite 数据库文件
│   ├── topic_index.txt   # 文章话题池
│   └── app.log           # 应用日志
│
├── prompts/
│   ├── article_gen.txt   # 文章生成 prompt（含阅读题和完形填空）
│   └── review_prompt.txt # 翻译批改 prompt
│
├── templates/
│   ├── index.html        # 主页：文章 + 阅读题 + 完形 + 翻译练习
│   ├── vocabulary.html   # 单词本页面
│   ├── flashcard.html    # 闪卡复习页面
│   ├── writing.html      # 写作练习页面
│   └── mistakes.html     # 错题本页面
│
└── static/
    ├── css/style.css     # 全局样式（含暗色模式）
    └── js/
        ├── app.js        # 主页面逻辑
        ├── translate.js  # 翻译练习模块
        └── tooltip.js    # 单词弹窗模块
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

编辑 `.env` 文件：

```env
# 必填
DEEPSEEK_API_KEY=your_deepseek_api_key

# 可选：使用 MySQL
DB_TYPE=mysql
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=
MYSQL_DATABASE=english_daily
```

不配置 MySQL 则默认使用 SQLite。

### 3. 启动应用

```bash
# 开发模式
python app.py

# 生产模式
gunicorn app:app -w 4 -b 0.0.0.0:5000
```

访问 `http://localhost:5000`

### 4. 手动生成文章

首次启动后没有文章，点击页面上的「立即生成」按钮，或调用 API：

```bash
curl -X POST http://localhost:5000/api/generate
```

首次生成约需 30-60 秒（包含文章、词汇表、5 道阅读题、10 空完形填空）。

## API 文档

| 路由 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 主页 |
| `/flashcard` | GET | 闪卡复习页 |
| `/writing` | GET | 写作练习页 |
| `/mistakes` | GET | 错题本页 |
| `/vocabulary` | GET | 单词本页 |
| `/api/article/today` | GET | 获取今日文章 |
| `/api/article/<id>` | GET | 获取指定文章 |
| `/api/articles` | GET | 获取文章列表 |
| `/api/generate` | POST | 手动生成文章 |
| `/api/word/mark-unfamiliar` | POST | 标记生词 |
| `/api/word/status` | POST | 更新单词状态 |
| `/api/word/delete/<id>` | DELETE | 删除单词 |
| `/api/stats` | GET | 学习统计 |
| `/api/translate` | POST | 翻译查询 |
| `/api/exercise/submit` | POST | 提交翻译练习 |
| `/api/reading/submit` | POST | 提交阅读理解答案 |
| `/api/cloze/submit` | POST | 提交完形填空答案 |
| `/api/writing/generate` | POST | 生成写作题目 |
| `/api/writing/submit` | POST | 提交写作批改 |
| `/api/writing/history` | GET | 写作历史 |
| `/api/flashcard/due` | GET | 获取待复习单词 |
| `/api/flashcard/review` | POST | 提交闪卡复习结果 |
| `/api/checkin` | POST | 每日打卡 |
| `/api/checkin/status` | GET | 打卡状态 |
| `/api/mistakes` | GET | 错题列表 |
| `/api/mistakes/<id>/review` | POST | 标记错题已复习 |
| `/api/mistakes/stats` | GET | 错题统计 |
| `/api/health` | GET | 健康检查 |

## 数据库表

| 表名 | 说明 |
|------|------|
| articles | 文章主表 |
| glossary | 词汇表 |
| word_lookups | 单词本/查词记录 |
| translation_exercises | 翻译练习 |
| reading_questions | 阅读理解题 |
| reading_answer_records | 阅读理解答题记录 |
| cloze_exercises | 完形填空 |
| cloze_answer_records | 完形填空答题记录 |
| writing_exercises | 写作题目 |
| writing_submissions | 写作提交记录 |
| spaced_repetition | 间隔记忆调度 |
| daily_checkins | 每日打卡 |
| mistake_notebook | 错题本 |

## 键盘快捷键

| 快捷键 | 功能 |
|--------|------|
| `T` | 展开/折叠所有句子翻译 |
| `←` / `→` | 上一篇/下一篇文章 |
| `空格` 或 `Enter` | 闪卡翻转 |
| `1 2 3 4` | 闪卡评分（翻转后） |
| `Esc` | 关闭弹窗 |

## 许可

MIT
