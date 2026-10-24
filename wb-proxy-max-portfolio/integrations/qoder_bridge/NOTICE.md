# Qoder 签名桥来源与许可

本目录的 `install.cjs`、`auth.cjs`、`signer.cjs` 移植自：

- AgentHub v1.77.0（https://github.com/HUIdada1/AgentHub）
- 上游路径：`electron/backend/proxy/qoderInstall.cjs`、`qoderAuth.cjs`、`qoderSigner.cjs`
- Copyright (c) 2026 沐辉 (HUIdada1)
- 许可：MIT License + 附加使用条款（禁止商业用途、禁止二次分发牟利、禁止批量账号运营等）

本项目仅在作者本人/小团队非商业自用场景下使用，并保留上游版权与许可声明。
完整条款见上游仓库 `LICENSE`。`bridge.cjs` 为本项目新增的 Python↔Node RPC 外壳
（上游无对应实现）。

签名桥需要本机安装并登录 Qoder 客户端：它从客户端安装目录提取 wasm 签名器，
用于生成每请求签名与 `Encode=1` 请求体。客户端升级导致结构变化时，通常需要
按上游同款逻辑更新 `signer.cjs` 的提取正则。
