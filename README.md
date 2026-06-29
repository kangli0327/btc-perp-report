# BTC-USDT 永续合约 4 小时决策网页

这个项目会通过 GitHub Actions 每 4 小时生成一次 BTC-USDT 永续合约投资决策 HTML 页面，并发布到 GitHub Pages。

## 输出内容

- `site/index.html`：最新报告，GitHub Pages 首页展示。
- `site/reports/YYYY-MM-DD-HHMM.html`：历史归档报告。

## GitHub Secrets

在 GitHub 仓库的 `Settings -> Secrets and variables -> Actions -> New repository secret` 中添加：

- `POSITION_CONFIG_JSON`：当前账户与双向持仓。
- `PREFERENCE_CONFIG_JSON`：投资偏好和风控参数。

可以参考 `config/position.example.json` 和 `config/preference.example.json`。

> 注意：Secrets 不会进入源码仓库，但生成后的 GitHub Pages 是公开网页。报告里展示的仓位、成本和建议会公开可见。

## 手动运行

GitHub Actions 支持 `workflow_dispatch` 手动触发。触发后会重新生成报告并发布到 Pages。

如果在本地已有 Python 3.11+，也可以运行：

```bash
python -m btc_report.generate
```

默认输出到 `site/`。

## GitHub Pages 设置

1. 推送本项目到 GitHub 仓库。
2. 打开仓库 `Settings -> Pages`。
3. `Build and deployment` 选择 `GitHub Actions`。
4. 在 `Actions` 页手动运行 `Build and deploy BTC report`。

