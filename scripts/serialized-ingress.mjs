// One process-wide lane. Completion means the full upstream HTTP response, not
// response headers or a downstream disconnect. Native durable-commit proof is
// still required before this lane can be accepted as a launch topology.
export class IngressError extends Error {
  constructor(code) { super(code); this.code=code; }
}

export function createSerializedIngress({maxQueuedRequests=32,queueWaitMs=10000}={}) {
  if(!Number.isInteger(maxQueuedRequests)||maxQueuedRequests<0||maxQueuedRequests>128 ||
      !Number.isInteger(queueWaitMs)||queueWaitMs<1||queueWaitMs>30000) {
    throw new Error('Invalid serialized ingress queue configuration.');
  }
  const pending=[];
  let active=false,closed=false;

  function rejectWaiting(entry,code) {
    const index=pending.indexOf(entry);
    if(index<0)return;
    pending.splice(index,1);
    clearTimeout(entry.waitTimer);
    entry.signal?.removeEventListener('abort',entry.abort);
    entry.reject(new IngressError(code));
  }

  function close() {
    // No reset API: reopening requires coordinated backend + gateway restart.
    closed=true;
    for(const entry of [...pending])rejectWaiting(entry,'SERIALIZATION_CLOSED');
  }

  function start(entry) {
    active=true;
    clearTimeout(entry.waitTimer);
    entry.signal?.removeEventListener('abort',entry.abort);
    const controller=new AbortController();
    let settled=false;
    const deadline=setTimeout(()=>{
      if(settled)return;
      settled=true;
      close();
      entry.reject(new IngressError('UPSTREAM_DEADLINE'));
      controller.abort();
    },entry.timeoutMs);
    Promise.resolve().then(()=>entry.task(controller.signal)).then(value=>{
      if(!settled){settled=true;entry.resolve(value);}
    },()=>{
      // A socket failure cannot establish that Jac stopped finalizing a write.
      close();
      if(!settled){settled=true;entry.reject(new IngressError('UPSTREAM_FAILURE'));}
    }).finally(()=>{
      clearTimeout(deadline);
      active=false;
      if(!closed&&pending.length)start(pending.shift());
    });
  }

  return {
    run(task,{signal,timeoutMs=30000}={}) {
      if(!Number.isInteger(timeoutMs)||timeoutMs<1||timeoutMs>80000) {
        return Promise.reject(new Error('Invalid upstream deadline.'));
      }
      if(closed)return Promise.reject(new IngressError('SERIALIZATION_CLOSED'));
      if(signal?.aborted)return Promise.reject(new IngressError('QUEUE_ABORTED'));
      if(active&&pending.length>=maxQueuedRequests)return Promise.reject(new IngressError('QUEUE_FULL'));
      return new Promise((resolve,reject)=>{
        const entry={task,signal,timeoutMs,resolve,reject};
        if(!active){start(entry);return;}
        entry.abort=()=>rejectWaiting(entry,'QUEUE_ABORTED');
        entry.waitTimer=setTimeout(()=>rejectWaiting(entry,'QUEUE_DEADLINE'),queueWaitMs);
        signal?.addEventListener('abort',entry.abort,{once:true});
        pending.push(entry);
      });
    },
    close,
    status:()=>({enabled:true,active,queued:pending.length,closed}),
  };
}
