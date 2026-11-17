// Test-only inherited listener; never release a selected origin and rebind it.
export async function listenOwnedCostSocket(server, config) {
  const origin = new URL(config.origin)
  if (origin.protocol !== "http:" || origin.hostname !== "127.0.0.1" || !origin.port ||
      origin.username || origin.password || origin.pathname !== "/" || origin.search || origin.hash ||
      !Number.isSafeInteger(config.listener_fd) || config.listener_fd < 3) {
    throw new Error("owned_dashboard_listener_required")
  }
  await new Promise((resolve, reject) => {
    const failed = (error) => { server.off("listening", ready); reject(error) }
    const ready = () => { server.off("error", failed); resolve() }
    server.once("error", failed)
    server.once("listening", ready)
    try { server.listen({ fd: config.listener_fd }) }
    catch (error) { server.off("error", failed); server.off("listening", ready); reject(error) }
  })
  const address = server.address()
  if (!address || address.address !== "127.0.0.1" || `http://127.0.0.1:${address.port}` !== config.origin) {
    await new Promise((resolve) => server.close(resolve))
    throw new Error("dashboard_listener_origin_mismatch")
  }
}
