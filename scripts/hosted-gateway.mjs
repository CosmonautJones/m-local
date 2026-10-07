import { createShareProxy } from './phone-share-proxy.mjs';

const port = Number(process.env.PORT || 10000);
const upstreamPort = Number(process.env.MLOCAL_BACKEND_PORT || 8200);
const ingress = process.env.MLOCAL_INGRESS || 'direct';
if (!Number.isInteger(port) || port < 1 || port > 65535 ||
    !Number.isInteger(upstreamPort) || upstreamPort < 1 || upstreamPort > 65535 ||
    !['direct', 'render', 'funnel', 'restricted-edge'].includes(ingress)) {
  throw new Error('Invalid hosting port or MLOCAL_INGRESS.');
}
const production = process.env.MLOCAL_ENV?.trim().toLowerCase() === 'production';
if (production && (ingress === 'direct' || process.env.MLOCAL_TRUSTED_HTTPS_EDGE !== '1' ||
    process.env.MLOCAL_PUBLIC_INGRESS !== 'restricted' ||
    process.env.MLOCAL_DEPLOYMENT_TOPOLOGY !== 'single-instance-serialized' ||
    process.env.MLOCAL_APP_REPLICAS !== '1')) {
  throw new Error('Production gateway requires restricted ingress, one serialized backend, and an explicitly verified HTTPS edge.');
}
// Generic Linux hosting keeps both processes private. A provider may select
// render only after proving its network exposes the gateway exclusively.
const loopback = ingress === 'funnel' || ingress === 'restricted-edge';
const proxy = createShareProxy({
  upstreamHost: '127.0.0.1', upstreamPort,
  trustCloudflare: ingress === 'render', trustFunnel: ingress === 'funnel', healthCheck: true,
  deploymentTopology: process.env.MLOCAL_DEPLOYMENT_TOPOLOGY || '',
  secureProductionIngress: production,
});
proxy.on('error', error => { console.error(error.message); process.exitCode = 1; });
proxy.listen(port, loopback ? '127.0.0.1' : '0.0.0.0', () => console.log(`M-Local gateway listening on port ${port}.`));
const stop = () => { proxy.closeAllConnections(); proxy.close(); };
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
