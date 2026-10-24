/*
 * panel/composables/poll.js —— 轮询 composable（本地自研，上游无对应）
 *
 * 全站唯一轮询实现，页面不再自写 setInterval：
 *
 *   const poller = createPoller(fn, ms, { guard, until });
 *   poller.start();   // 启动（已在跑会先清旧再起新）
 *   poller.stop();    // 停止（可重复调用）
 *   poller.active;    // 是否在跑
 *
 *   fn          轮询体（可为 async），自带错误处理，poller 不因抛错停止
 *   opts.guard  () => bool —— 每轮先判，假则跳过本轮（定时器继续跑）
 *   opts.until  (result) => truthy —— fn 返回值命中即自动 stop()
 */
export function createPoller(fn, ms, opts = {}) {
  const { guard, until } = opts;
  let timer = null;

  function start() {
    if (timer) stop();
    timer = setInterval(() => {
      if (guard && !guard()) return;
      Promise.resolve(fn())
        .then((result) => { if (until && until(result)) stop(); })
        .catch(() => {});
    }, ms);
  }

  function stop() {
    if (timer) {
      clearInterval(timer);
      timer = null;
    }
  }

  return {
    start,
    stop,
    get active() { return timer != null; },
  };
}
