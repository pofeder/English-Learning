# 本地学习资源

## 下载并导入公开字典

项目内置了一组考研高频词，词义存储在 `word_definitions` 表中。需要扩大词库时，可以下载公开、允许再分发的字典文件：

```bash
python scripts/download_learning_resources.py download \
  --url https://raw.githubusercontent.com/skywind3000/ECDICT/master/ecdict.csv \
  --output data/downloads/ecdict.csv

python scripts/download_learning_resources.py import-dictionary \
  --path data/downloads/ecdict.csv
```

支持 CSV 和 JSON。导入后，文章点击查词只查询本地数据库，不调用 AI。

## 导入考研题库

题库下载器支持用户拥有授权的 JSON/CSV 文件，并会检查题干和 A-D 选项字段：

```bash
python scripts/download_learning_resources.py download-question-bank \
  --url <授权题库地址> \
  --output data/downloads/kaoyan_questions.json
```

考研真题通常受版权保护，请使用学校、出版社或自己拥有授权的题库文件。
