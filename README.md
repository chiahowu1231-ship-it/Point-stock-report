# Point Stock Daily Report (GitHub Actions)

這個專案會在 **每週一～五 台灣時間 16:00（UTC 08:00）** 自動執行：

1. 依照 `src/config.py` 的分點清單抓取資料
2. 產生報表：`output/IKE_Report_YYYYMMDD.xlsx` 與 `output/IKE_Report_YYYYMMDD.pdf`
3. Email 附件寄出（To + BCC 由 GitHub Secrets 控制）
4. 同步上傳 GitHub Actions artifacts，並設定 `retention-days: 7` 自動清除

## Secrets 設定（Repo Settings → Secrets and variables → Actions）

- SMTP_HOST = smtp.gmail.com
- SMTP_PORT = 587
- SMTP_USER = 你的 Gmail（例如 chiahowu1231@gmail.com）
- SMTP_PASS = Gmail **App Password**（16 碼）
- MAIL_FROM = 寄件者（通常同 SMTP_USER）
- MAIL_TO = 收件者（你自己）
- MAIL_BCC = 逗號分隔的 BCC 名單

## 本機測試

```bash
pip install -r requirements.txt
python src/run_report.py
# 設定好環境變數後才可測試寄信
python src/mailer.py
```

## GitHub Actions

- Workflow 檔：`.github/workflows/daily_report.yml`
- 也支援手動觸發：Actions → Run workflow
