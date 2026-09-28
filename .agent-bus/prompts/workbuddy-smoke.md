你是本项目（C:\Users\21986\Desktop\ican\AI-PR-Review-Assistant）的协作 agent（workbuddy）。
这是一次**链路自检**任务，刻意做得很小，用来确认 WorkBuddy 已经能接入协作总线。

## 要做的事
1. 读 `README.md` 的前 40 行（只读）。
2. 把 3 条要点写进新文件 `docs/workbuddy-smoke.md`（只写这一个文件，别碰其它文件），格式：
   ```
   # WorkBuddy 协作链路自检

   - agent: workbuddy
   - 读到 README 前 40 行，要点：
     1) <要点1>
     2) <要点2>
     3) <要点3>
   - 结论：workbuddy 已可被 agent_dispatch_runner 无头驱动并写文件。
   ```
3. 不要运行测试、不要改源码、不要 git 操作、不要读取任何凭据。

## 完成后
按总线报告：
`python scripts/agent_bridge.py report workbuddy-smoke --agent workbuddy --status completed --summary "WorkBuddy 链路自检通过" --evidence "docs/workbuddy-smoke.md 已写入；README 前 40 行要点<...>" --blocker "无"`
