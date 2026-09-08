const net = require("node:net");
const { execFileSync } = require("node:child_process");

const kubectl = process.env.KUBECTL || "kubectl";
const context = process.env.KUBE_CONTEXT || "orbstack";
const namespace = process.env.KUBE_NAMESPACE || "job-radar-coach";
const service = JSON.parse(execFileSync(kubectl, [
  "--context", context, "-n", namespace, "get", "service/livekit", "-o", "json",
], { encoding: "utf8" }));
const host = service.spec.clusterIP;
if (!net.isIP(host)) throw new Error("LiveKit Service has no concrete cluster IP");

function port(name, fallback) {
  const value = Number(process.env[name] || fallback);
  if (!Number.isInteger(value) || value < 1 || value > 65535) throw new Error(`${name} is not a valid port`);
  return value;
}
const routes = [
  [port("VOICE_BRIDGE_HTTP_PORT", 17880), port("LIVEKIT_SERVICE_HTTP_PORT", 7880)],
  [port("VOICE_BRIDGE_RTC_PORT", 17881), port("LIVEKIT_SERVICE_RTC_PORT", 7881)],
];

const sockets = new Set();
const servers = routes.map(([local, remote]) => net.createServer(client => {
  const upstream = net.connect({ host, port: remote });
  sockets.add(client); sockets.add(upstream);
  const close = () => {
    client.destroy(); upstream.destroy(); sockets.delete(client); sockets.delete(upstream);
  };
  client.on("error", close);
  upstream.on("error", error => { console.error(`upstream ${remote}: ${error.code}`); close(); });
  client.on("close", close); upstream.on("close", close);
  client.pipe(upstream).pipe(client);
}).listen(local, "127.0.0.1", () => console.log(`loopback ${local} -> LiveKit service ${remote}`)));

process.on("SIGTERM", () => {
  for (const socket of sockets) socket.destroy();
  for (const server of servers) server.close();
});
