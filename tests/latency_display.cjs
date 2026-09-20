const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const patch=fs.readFileSync(path.join(__dirname,'../patches/flowsense/0001-show-mean-rtt-and-stale-samples.patch'),'utf8');
const added=patch.split('\n').filter(l=>l.startsWith('+')&&!l.startsWith('+++')).map(l=>l.slice(1)).join('\n');
const source=added.slice(added.indexOf('function latencyState('),added.indexOf('\n}\n')+3);
const fn=vm.runInNewContext('(function(){'+source+';return latencyState;})()', {latencyColor:()=> '#00cc44',Date:{now:()=>1000000}});
const good={avg_ping:0, samples:1,attempts:1,loss_percent:0,available:true,updated_at:1000,interval:5};
assert.equal(fn(good).label,'0.0ms');
assert.equal(fn({...good,avg_ping:12.3}).label,'12.3ms');
assert.equal(fn({...good,updated_at:900}).label,'Stale');
assert.equal(fn({...good,updated_at:1200}).label,'Stale');
assert.equal(fn({...good,avg_ping:null,samples:0,reachable:false}).label,'No replies');
assert.equal(fn({available:false}).label,'N/A');
assert.equal(fn({...good,avg_ping:15,jitter:1.25,samples:6,attempts:12,loss_percent:50,reachable:false,target:'1.1.1.1'}).detail,
  'Jitter: 1.3ms | 6/12 replies | 1.1.1.1');
console.log('Latency display distinguishes valid zero, stale samples and no replies.');
