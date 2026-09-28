"""Execute the production ucode with a fake kernel filesystem, no live writes."""
from pathlib import Path
import json
ROOT = Path(__file__).resolve().parents[1]
import shutil, subprocess, unittest
ROLES = ['rx0','wm','wa','wa0','rx2','wa2','rro0','rro2','pg0','pg1','pg2','tf0','tf2','ind','npu0','npu1']

def fixture(wifi=True):
    files = {'/tmp/sysinfo/board_name': 'gemtek,w1700k-ubi',
             '/sys/devices/system/cpu/online': '0-3',
             '/proc/sys/net/core/rps_sock_flow_entries':'0'}
    globs = {'/sys/class/net/*': [], '/proc/[0-9]*/status': []}
    links = {}
    globs['/sys/class/ieee80211/*']=['/sys/class/ieee80211/phy0'] if wifi else []
    if wifi:
        links['/sys/class/ieee80211/phy0/device/driver']='/drivers/mt7996e'
        files['/sys/kernel/debug/ieee80211/phy0/mt76/napi_threaded']='1'
    for dev, driver in [('eth0','airoha_eth'),('eth1','airoha_eth')] + ([('wlan0','mt7996e')] if wifi else []):
        path='/sys/class/net/'+dev
        globs['/sys/class/net/*'].append(path)
        links[path+'/device/driver']='/drivers/'+driver
        files[path+'/phy80211/index']='0'
        globs[path+'/queues/rx-*/rps_cpus']=[]
        for q in range(1 if driver=='mt7996e' else 32):
            qp=f'{path}/queues/rx-{q}/'
            globs[path+'/queues/rx-*/rps_cpus'].append(qp+'rps_cpus')
            files[qp+'rps_cpus']='f'
            files[qp+'rps_flow_cnt']='0'
    names=[]
    for qdma in range(2):
        names += [f'napi/qdma{qdma}-r{q}' for q in range(32)]
        names += [f'napi/qdma{qdma}-t{q}' for q in range(2)]
    if wifi: names += ['napi/phy0-'+role for role in ROLES]
    for i,name in enumerate(names,100):
        path=f'/proc/{i}/status'
        files[path]=f'Name:\t{name}\nCpus_allowed_list:\t0-3\n'
        globs['/proc/[0-9]*/status'].append(path)
    # A reversed discovery order must not reverse the hardware identities.
    globs['/proc/[0-9]*/status'].reverse()
    irqs=[(42+i,f'airoha_eth.{i}') for i in range(8)]
    if wifi: irqs += [(36,'mt76-npu.0'),(37,'mt76-npu.1'),(54,'mt7996e'),(55,'mt7996e-hif')]
    lines=[]
    for irq,name in irqs:
        lines.append(f' {irq}: 100 0 0 0 GICv3 12 Level {name}')
        files[f'/proc/irq/{irq}/smp_affinity_list']='0-3'
        files[f'/proc/irq/{irq}/effective_affinity_list']='0'
    files['/proc/interrupts']='\n'.join(lines)
    return dict(files=files,glob=globs,links=links)

cases=[]
def case(name, mode='1', error=None, edit=None, **extra):
    state=fixture()
    if edit: edit(state)
    cases.append(dict(name=name,mode=mode,flows=extra.pop('flows',256),error=error,state=state,**extra))
case('locality')
case('clear_previous_rps_rfs', edit=lambda s:s['files'].update({p:'256' for p in s['files'] if p.endswith('/rps_flow_cnt')}))
case('locality_ignores_positive_flows', flows=4096)
case('locality_keeps_global_table_for_other_devices', edit=lambda s:s['files'].update({'/proc/sys/net/core/rps_sock_flow_entries':'65536'}))
def old_wifi_cpu(s):
    for i in range(168,184):
        p=f'/proc/{i}/status'
        s['files'][p]=s['files'][p].replace('0-3','0')
    for irq in (36,37):
        s['files'][f'/proc/irq/{irq}/smp_affinity_list']='0'
        s['files'][f'/proc/irq/{irq}/effective_affinity_list']='0'
case('migrate_wifi_from_cpu0', edit=old_wifi_cpu)
case('correct_stale_effective_irq',edit=lambda s:s['files'].update({'/proc/irq/42/smp_affinity_list':'1','/proc/irq/42/effective_affinity_list':'3'}))
case('disabled','0')
case('rps_with_rfs','2')
case('round_flow_count','2',flows=129)
case('preserve_larger_global','2',edit=lambda s:s['files'].update({'/proc/sys/net/core/rps_sock_flow_entries':'65536'}))
case('old_kernel',error='identity kernel patch',edit=lambda s:s['files'].update({'/proc/100/status':'Name:\tnapi/qdma_eth-0\nCpus_allowed_list:\t0-3\n'}))
case('wrong_board',error='Gemtek',edit=lambda s:s['files'].update({'/tmp/sysinfo/board_name':'other'}))
case('offline_core',error='CPUs 0-3',edit=lambda s:s['files'].update({'/sys/devices/system/cpu/online':'0-2'}))
case('missing_ring',error='Expected 32 RX',edit=lambda s:s['glob']['/proc/[0-9]*/status'].remove('/proc/100/status'))
case('duplicate_ring',error='Unexpected QDMA',edit=lambda s:s['files'].update({'/proc/101/status':s['files']['/proc/100/status']}))
case('missing_irq',error='eight QDMA',edit=lambda s:s['files'].update({'/proc/interrupts':s['files']['/proc/interrupts'].replace('airoha_eth.7','other.7')}))
case('wifi_irq_other_cpu',error='confined to CPU0',edit=lambda s:s['files'].update({'/proc/interrupts':s['files']['/proc/interrupts'].replace('55: 100 0 0 0','55: 100 1 0 0')}))
case('rfs_global_absent','2',error='Cannot read',edit=lambda s:s['files'].pop('/proc/sys/net/core/rps_sock_flow_entries'))
case('rfs_queue_absent','2',error='Cannot read',edit=lambda s:s['files'].pop('/sys/class/net/eth1/queues/rx-31/rps_flow_cnt'))
case('flows_out_of_range','2',flows=8192,error='between 16 and 4096')
case('rollback_irq_write',fail='/proc/irq/46/smp_affinity_list')
case('rollback_npu_irq_write',fail='/proc/irq/37/smp_affinity_list')
case('rollback_wifi_task',fail='task:175')
case('rollback_napi_task',fail='task:130')
case('rollback_rfs_write','2',fail='/sys/class/net/eth1/queues/rx-31/rps_flow_cnt')
case('rollback_rps_write','2',fail='/sys/class/net/wlan0/queues/rx-0/rps_cpus',edit=lambda s:s['files'].update({'/sys/class/net/wlan0/queues/rx-0/rps_cpus':'0'}))
case('effective_irq_mismatch',wrong_effective='/proc/irq/46/effective_affinity_list')
case('missing_wifi_napi',error='Missing Wi-Fi NAPI',edit=lambda s:s['glob'].update({'/proc/[0-9]*/status':s['glob']['/proc/[0-9]*/status'][16:]}))
cases.append(dict(name='ethernet_only',mode='1',flows=256,state=fixture(False)))


case('threaded_disabled',error='Threaded NAPI',edit=lambda s:s['files'].update({'/sys/kernel/debug/ieee80211/phy0/mt76/napi_threaded':'0'}))
case('anonymous_wifi',error='RX queue role kernel patch',edit=lambda s:s['files'].update({'/proc/168/status':'Name:\tnapi/phy0-0\nCpus_allowed_list:\t3\n'}))
case('unknown_wifi_role',error='Unexpected Wi-Fi',edit=lambda s:s['files'].update({'/proc/168/status':'Name:\tnapi/phy0-new\nCpus_allowed_list:\t3\n'}))
case('duplicate_wifi_role',error='Unexpected Wi-Fi',edit=lambda s:s['files'].update({'/proc/169/status':s['files']['/proc/168/status']}))
case('missing_npu_irq',error='both NPU',edit=lambda s:s['files'].update({'/proc/interrupts':s['files']['/proc/interrupts'].replace('mt76-npu.1','other')}))
case('duplicate_npu_irq',error='Duplicate NPU',edit=lambda s:s['files'].update({'/proc/interrupts':s['files']['/proc/interrupts'].replace('mt76-npu.1','mt76-npu.0')}))
case('single_queue_missing',error='Missing Wi-Fi NAPI',edit=lambda s:s['glob']['/proc/[0-9]*/status'].remove('/proc/170/status'))
def no_wifi_netdev(s):
    s['glob']['/sys/class/net/*'].remove('/sys/class/net/wlan0')
    for p in list(s['files']):
        if p.startswith('/sys/class/net/wlan0/'):
            del s['files'][p]
case('wifi_without_ap_sta_netdev',edit=no_wifi_netdev)

mock=r'''
let state, current, events, failures;
function readfile(path) { return state.files[path]; }
function realpath(path) { return state.links[path]; }
function glob(pattern) { return state.glob[pattern] ?? []; }
function inject(path) {
    if (current.fail == path && !failures) { failures++; return true; }
    return false;
}
function writefile(path, value) {
    push(events, {path, value});
    if (inject(path)) return null;
    state.files[path] = value;
    if (match(path, /smp_affinity_list$/)) {
        let effective=replace(path,/smp_affinity_list$/, 'effective_affinity_list');
        state.files[effective] = effective == current.wrong_effective ? '3' : value;
    }
    return length(value);
}
function system(cmd) {
    let m=match(cmd, /^taskset -pc ([0-9,-]+) (\d+) >\/dev\/null$/);
    if (!m) die(`Unexpected command: ${cmd}`);
    push(events, {pid: m[2], value: m[1]});
    if (inject(`task:${m[2]}`)) return 1;
    let p=`/proc/${m[2]}/status`;
    state.files[p]=replace(state.files[p], /Cpus_allowed_list:[^\n]+/, `Cpus_allowed_list:\t${m[1]}`);
    return 0;
}
function check(condition, msg) { if (!condition) die(`${current.name}: ${msg}`); }
'''
source=(ROOT/'package/w1700k-custom/root/usr/libexec/w1700k-affinity.uc').read_text()
source=source.split('// CLI\n')[0].removeprefix('#!/usr/bin/env ucode\n').replace("import { glob, readfile, writefile, realpath } from 'fs';",mock)
tests=r'''
let results=[];
for (let test in cases) {
    current=test; state=test.state; events=[]; failures=0;
    let original={...state.files}, plan, failure;
    try { plan=build_plan(test.mode,test.flows); } catch (err) { failure=''+err; }
    check(length(events)==0,'planning must never write');
    if (test.error) {
        check(failure && index(failure,test.error)>=0,`wrong preflight error: ${failure}`);
        push(results,{name:test.name, passed:true, rejected:failure});
        continue;
    }
    check(!failure, `unexpected preflight: ${failure}`);
    let applied_failure;
    try { apply_plan(plan); } catch (err) { applied_failure=''+err; }
    if (test.fail || test.wrong_effective) {
        check(applied_failure,'failure injection did not fail');
        for (let p in keys(original)) {
            if (match(p,/effective_affinity_list$/)) continue;
            check(original[p]==state.files[p],`rollback mismatch: ${p}`);
        }
        push(results,{name:test.name,passed:true,rollback:true});
        continue;
    }
    check(!applied_failure,`apply failure: ${applied_failure}`);
    for (let p in keys(state.files)) {
        if (match(p,/rps_cpus$/)) check(state.files[p]==(test.mode=='2'?'f':'0'),`RPS ${p}`);
        if (match(p,/rps_flow_cnt$/)) check(state.files[p]==(test.mode=='2'?'256':'0'),`RFS ${p}`);
    }
    for (let i=100; i<168; i++)
        check(task_info(i).cpus==(test.mode=='0'?'0-3':(i<134?'1':'2')),`QDMA mapping ${i}`);
    for (let i=168; i<184; i++) {
        if (!state.files[`/proc/${i}/status`]) break;
        check(task_info(i).cpus==(test.mode=='0'?'0-3':(i>=182?'3':'0')),`Wi-Fi mapping ${i}`);
    }
    for (let i=42; i<50; i++)
        check(state.files[`/proc/irq/${i}/smp_affinity_list`]==(test.mode=='0'?'0-3':(i<46?'1':'2')),`IRQ mapping ${i}`);
    for (let irq in [36,37]) {
        let p=`/proc/irq/${irq}/smp_affinity_list`;
        if (state.files[p] != null)
            check(state.files[p]==(test.mode=='0'?'0-3':'3'),`NPU IRQ mapping ${irq}`);
    }
    for (let irq in [54,55])
        check(state.files[`/proc/irq/${irq}/smp_affinity_list`]==original[`/proc/irq/${irq}/smp_affinity_list`],'PCIe MSI must not be written');
    if (test.mode!='2')
        check(state.files['/proc/sys/net/core/rps_sock_flow_entries']==original['/proc/sys/net/core/rps_sock_flow_entries'],'global table of other devices must not be changed');
    if (test.mode=='2') {
        check(+state.files['/proc/sys/net/core/rps_sock_flow_entries']>=32768,'RFS global disabled');
        let rps_index=-1, rfs_index=-1;
        for (let i=0;i<length(events);i++) {
            if (events[i].path && match(events[i].path,/rps_cpus$/) && events[i].value=='f' && rps_index<0) rps_index=i;
            if (events[i].path && match(events[i].path,/rps_flow_cnt$/)) rfs_index=i;
        }
        check(rps_index<0 || rps_index>rfs_index,'RPS enabled before RFS');
    }
    let second=build_plan(test.mode,test.flows);
    check(length(second)==0,'reload must be idempotent');
    push(results,{name:test.name,passed:true,changes:length(plan)});
}
print(sprintf('%J\n',results));
'''

def program():
    return 'let cases='+json.dumps(cases)+';\n'+source+tests

class AffinityPolicy(unittest.TestCase):
    @unittest.skipUnless(shutil.which('ucode'), 'ucode host interpreter unavailable; fixtures can run on the target without kernel writes')
    def test_mocked_kernel_policy(self):
        r=subprocess.run(['ucode','-'],input=program(),text=True,capture_output=True)
        self.assertEqual(r.returncode,0,r.stderr)
        results=json.loads(r.stdout)
        self.assertEqual(len(results),len(cases))
        self.assertTrue(all(x['passed'] for x in results))

if __name__=='__main__':
    unittest.main()
