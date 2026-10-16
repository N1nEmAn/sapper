# TSecBench 托管模式配置清单（王座协议线上赛）

正式赛规则要点（2026-10-17 00:00 — 10-18 23:59）：

- **只有 1 次评测机会**，仅队长账号可提交；Agent 异常没有重试
- 50 题 / 100 flag，任务限时 **8 小时**（镜像内默认按 470 分钟跑，留安全边际）
- 无 hint（接口返回 null，也无惩罚）
- 排名顺序：**得分 → 有效耗时 → token 量**（所以默认不开 verify 双检，省 token）
- 模型限流/超时/中断不算平台异常——镜像内已带**模型调用重试**（SAPPER_RETRY_MODEL=3，指数退避），单题异常自动跳过下一轮再试，绝不中断整个任务
- 严禁引导 Agent 攻击平台——提示词中已有 scope 纪律，请勿在模板里加任何"打平台"的引导

## 一、平台自动注入（控制台不要手填）

| 变量 | 说明 |
|---|---|
| `BENCHMARK_BASE_URL` | 答题 API 基址，任务创建后自动注入 |
| `BENCHMARK_TOKEN` | 答题 API 凭证，自动注入 |

## 二、运行时环境变量（控制台手填）

| KEY | VALUE | 说明 |
|---|---|---|
| `ANTHROPIC_BASE_URL` | `http://open.bigmodel.cn.tsecbench.gw/api/anthropic` | 白名单域名 + `.tsecbench.gw` 后缀，https→http |
| `ANTHROPIC_AUTH_TOKEN` | 你的智谱 API Key | 换供应商只改这项和 BASE_URL |
| `SAPPER_MODEL` | `glm-5.3-flash[1m]` | 已实测走通。`[1m]` 后缀由 claude CLI 解析为 1M 上下文（剥后缀 + beta 头），API 侧模型名仍是 glm-5.3-flash，直接填 `glm-5.3-flash-1m` 会报模型不存在 |

### Key 池自动轮换（强烈建议配置）

当某个 Key 额度耗尽/401/欠费，系统自动切换到池中下一组凭据，`-p` 版**无需重启**（下一次模型调用即用新 Key），tmux 版自动轮换并重启对应 TUI（`claude --continue` 恢复原会话上下文）。检测特征：insufficient/balance/quota/exceeded/billing/401/unauthorized/欠费/余额。

| KEY | VALUE 格式 |
|---|---|
| `SAPPER_KEY_POOL` | `[{"base_url":"http://open.bigmodel.cn.tsecbench.gw/api/anthropic","token":"智谱key1","model":"glm-5.3-flash[1m]"},{"base_url":"http://api.moonshot.cn.tsecbench.gw/v1","token":"moonshot-key","model":"kimi-k2.5"}]` |

注意：池里各组 URL 都要按托管模式规则加 `.tsecbench.gw` 后缀（http）。单 Key 时轮换自动退化为普通重试。

可选调参（不填用镜像默认值）：

| KEY | 默认 | 说明 |
|---|---|---|
| `SAPPER_TOTAL_MINUTES` | `470` | 总预算（8h 限时留边际） |
| `SAPPER_MINUTES_PER_CHALLENGE` | `9` | 每题每轮 auto 分钟数；bench 多轮循环，没解完的题下轮续（进度在图里保留）。50 题×9 分≈450 分 |
| `SAPPER_MAX_STEPS` | `10` | 每题每轮最多 reason 轮数 |
| `SAPPER_RETRY_MODEL` | `3` | 模型调用失败重试次数（10s/20s/40s 退避） |
| `SAPPER_VERIFY` | 不设 | 设为 `1` 才开启核验者（费 token，正式赛默认不开） |

## 三、容器启动流程

1. 校验 `BENCHMARK_*` 与模型网关环境变量，缺失立刻 FATAL（日志可见）
2. 平台 API 连通性探测 + 模型 CLI 冒烟测试
3. `sapper bench --minutes 470`：对每个未完成题目循环
   `start → 建图（题目描述/靶标地址按不可信数据录入）→ auto 自主解题
   → 提交已记录未提交的 flag（正确/错误都回写）→ close`
   一轮做不完全部题就再来一轮，直到全部完成或 470 分钟用尽
4. 非特权用户运行（Claude Code 拒绝 root 下跳权限确认）；密钥全走环境变量，镜像不含任何密钥/题目记忆

## 四、一次机会的检查单（提交前自查）

- [ ] 用**其他题集**（如 Tsecbench v1 公开集）跑过完整托管评测，`correct_flag_count` 有增长
- [ ] 镜像内 `sapper --version`、`sapper bench --help` 正常
- [ ] `ANTHROPIC_*` 三个变量填的是 `.tsecbench.gw` 地址 + 正确 key
- [ ] 队长账号提交；活动期间只此一次
