// Public startup provenance only. No Git lookup, disk inventory or RPC here.
export const unknownBuildIdentity=Object.freeze({schema:1,status:'unknown',build_id:null,source_sha:null,source_tree:null,
  artifact_sha256:null,dependency_archive_sha256:null,serving_mode:null,verification:null});

export function parseBuildIdentity(value) {
  if(value===undefined||value===null||value==='')return unknownBuildIdentity;
  try {
    if(typeof value==='string') {
      if(value.length>4096)throw new Error();
      value=JSON.parse(value);
    }
    const keys=Object.keys(unknownBuildIdentity);
    if(!value||Array.isArray(value)||typeof value!=='object'||Object.keys(value).length!==keys.length||
       !keys.every(key=>Object.hasOwn(value,key))||value.schema!==1)throw new Error();
    if(value.status==='unknown') {
      if(!keys.every(key=>value[key]===unknownBuildIdentity[key]))throw new Error();
      return unknownBuildIdentity;
    }
    const sha=value=>typeof value==='string'&&/^(?:[a-f0-9]{40}|[a-f0-9]{64})$/.test(value);
    const digest=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
    if(value.status!=='known'||!sha(value.source_sha)||!sha(value.source_tree)||!digest(value.build_id)||
       !digest(value.artifact_sha256)||(value.dependency_archive_sha256!==null&&!digest(value.dependency_archive_sha256))||
       value.serving_mode!=='source-at-fixed-canonical-entry'||value.verification!=='launch-snapshot')throw new Error();
    return Object.freeze(Object.fromEntries(keys.map(key=>[key,value[key]])));
  } catch {throw new Error('Invalid M-Local build identity.');}
}

export function buildIdentityPage(value) {
  const identity=parseBuildIdentity(value);
  const details=identity.status==='known'
    ? `<p>Package identity checked when this gateway started.</p><dl><dt>Build ID</dt><dd>${identity.build_id}</dd>`+
      `<dt>Source revision</dt><dd>${identity.source_sha}</dd><dt>Packaged artifact</dt><dd>${identity.artifact_sha256}</dd></dl>`+
      '<p>This identifies the admitted source build. It does not certify current readiness or exact bytes served to your browser.</p>'
    : '<p>Build unknown. No verified packaged build metadata was supplied at startup.</p>';
  return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'+
    '<title>M-Local build</title><style>body{font:1rem system-ui;max-width:48rem;margin:3rem auto;padding:0 1rem}dd{margin:0 0 1rem;overflow-wrap:anywhere;font-family:monospace}</style></head><body><main><h1>M-Local build</h1>'+
    details+'<p><a href="/version.json">Build metadata (JSON)</a> | <a href="/">Back to M-Local</a></p></main></body></html>';
}
