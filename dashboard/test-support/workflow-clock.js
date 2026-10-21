// Only explicitly configured invented workflow tests install this wall clock.
// Timers and elapsed-time coordinates remain real.
export function installWorkflowClock(metadata) {
  const RealDate = globalThis.Date
  const fixed = RealDate.parse(metadata.fixed_at)
  if (!Number.isFinite(fixed) || !Number.isFinite(metadata.real_epoch)) throw new Error("Invalid invented workflow clock")
  const now = () => fixed + RealDate.now() - metadata.real_epoch * 1000
  globalThis.Date = new Proxy(RealDate, {
    apply() { return new RealDate(now()).toString() },
    construct(target, args, newTarget) { return Reflect.construct(target, args.length ? args : [now()], newTarget) },
    get(target, key, receiver) { return key === "now" ? now : Reflect.get(target, key, receiver) },
  })
  return () => { globalThis.Date = RealDate }
}
