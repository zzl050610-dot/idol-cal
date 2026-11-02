# IDOL CAL

把多个偶像团体的官方日历合并成一个页面看。自带 8 个团，随时可以再加。

## 启动

```bash
cd idolcal
python app.py
```

然后打开 <http://127.0.0.1:8899>

首次启动会抓一遍全部日历（约 30–60 秒），之后 30 分钟内走缓存，点「刷新」可以强制重抓。

## 功能

- **一键更新**：点「刷新」→ 后台抓取，按钮显示「更新中…」，完成后弹提示
- **自动更新**：底栏勾选后每 30 分钟自动跑一次；切回标签页时若数据超过 30 分钟也会自动刷
- **月历 / 列表**两种视图切换
- **点任意事件**弹出详情：团名、完整标题、日期时间、场地、备注、原始链接
- 顶部色块可**单独开关某个团**
- 点「+ 加团」直接填日历 ID 就能加，会自动读到团名
- 每格最多显示 4 条，多出来的点「+N 更多」跳到列表

## 加团

两种方式，效果一样：

1. **页面右上角「+ 加团」**
   - TimeTree：填公开日历链接里 `public_calendars/` 后面那段
     （`timetreeapp.com/public_calendars/hbn_187` → `hbn_187`）
   - Google Calendar：填公开日历的邮箱 ID，或整条 ICS 链接
2. **直接改 `groups.json`**

```json
{"name": "新团名", "short": "短名", "color": "#4a9", "type": "timetree", "id": "alias_code"}
```

`type` 支持 `timetree` / `gcal` / `ics`。

## 为什么必须跑在本地

TimeTree 的公开日历接口需要带自定义请求头 `X-Timetreea`，浏览器直接请求会被 CORS 和预检拦掉。所以由本地 Python 服务去抓，页面只跟 localhost 通信。纯静态托管（GitHub Pages 之类）做不到这一点。

## 文件

| 文件 | 作用 |
|---|---|
| `app.py` | 本地服务：抓日历、合并、提供 `/api/events` |
| `index.html` | 前端页面（单文件，无依赖） |
| `groups.json` | 团列表配置 |
| `cache.json` | 抓取缓存，删掉即重抓 |

## 部署到网上（GitHub Pages，免费）

不能直接把网页扔上去——TimeTree 那个接口要自定义请求头，浏览器会被 CORS 拦住。
所以改成「抓取在构建时做，页面纯静态」：

```
GitHub Actions（每小时）→ build_static.py → dist/ → GitHub Pages
```

步骤：

1. 建一个仓库，把 `idolcal/` 和 `.github/workflows/idolcal.yml` 一起推上去
2. 仓库 **Settings → Pages → Source** 选 **GitHub Actions**
3. 到 **Actions** 标签，选 `idolcal`，点 **Run workflow** 跑第一次
4. 地址是 `https://<用户名>.github.io/<仓库名>/`

之后每小时自动更新一次。手机上打开后可以「添加到主屏幕」，效果接近 App。

三个注意点：

- 免费版 Pages 要求仓库是 **public**（团名列表会公开，不涉及隐私）
- GitHub 的定时任务在仓库 **60 天没提交** 后会被暂停，随便改一下文件就恢复
- 静态版没有「加团」和真实的刷新按钮，点「重新载入」只是重新读一次 JSON

想要**真正的实时刷新按钮**，得用带后端的方案（Cloudflare Workers + KV，免费额度够用），
把 `app.py` 里的抓取逻辑搬成 Worker 就行。

## 已知限制

- 只依赖各团自己维护的日历，**日历没写就没有**（比如 i-COL 的日历 2021 年后就没更新了）
- 日历里的「出演辞退」「NO LIVE」等条目会原样显示
- 时间统一按 JST 显示
