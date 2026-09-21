"""Exercise the shared rate state machine used by both monitor views."""
from pathlib import Path
import json,shutil,subprocess,unittest
ROOT=Path(__file__).resolve().parents[1]

def backend_program():
    source=(ROOT/'package/w1700k-custom/root/usr/libexec/w1700k-frame-engine').read_text()
    source=source[source.index('function driver_counters()'):source.index("try { print(sprintf")]
    row=lambda name,rx=200,tx=100: f'{name}: 1000 {rx} 0 3 0 0 0 0 2000 {tx} 0 7 0 0 0 0'
    files={'/proc/net/dev': '\n'.join(row(n) for n in ('eth0','wan','lan2')),
           '/proc/uptime':'123.45 40.00','/proc/sys/kernel/random/boot_id':'fixture-boot',
           '/tmp/sysinfo/board_name':'gemtek,w1700k-ubi'}
    links={}
    for n,p in [('eth0',1),('wan',2),('lan2',4)]:
        links[f'/sys/class/net/{n}/of_node']=f'/sys/firmware/devicetree/base/soc/ethernet@1fb50000/ethernet@{p}'
        links[f'/sys/class/net/{n}/device/driver']='/sys/bus/platform/drivers/airoha_eth'
    cases=[]
    def case(name,change=None,expected=None):
        state=json.loads(json.dumps(dict(files=files,links=links,names=['eth0','wan','lan2'],output='\n'.join(['0x00000000']*31),status=0)))
        if change:change(state)
        cases.append(dict(name=name,state=state,expected=expected or {}))
    case('cumulative_driver_totals')
    case('no_traffic_is_valid_zero',lambda s:s['files'].update({'/proc/net/dev':'\n'.join(row(n,0,0) for n in s['names'])}),{'tx':0})
    case('missing_interface_is_unavailable',lambda s:s.update(names=['eth0','wan']),{'unavailable':'gdm4'})
    case('missing_stats_is_unavailable',lambda s:s['files'].update({'/proc/net/dev':row('eth0')+'\n'+row('wan')}),{'unavailable':'gdm4'})
    case('malformed_stats',lambda s:s['files'].update({'/proc/net/dev':row('eth0')+'\nwan: invalid\n'+row('lan2')}),{'unavailable':'gdm2'})
    case('unsupported_dt_is_not_guessed',lambda s:s['links'].update({'/sys/class/net/lan2/of_node':'/other/ethernet@4'}),{'unavailable':'gdm4'})
    case('non_airoha_driver_is_excluded',lambda s:s['links'].update({'/sys/class/net/lan2/device/driver':'/drivers/dsa'}),{'unavailable':'gdm4'})
    def rename(s):
        s['names'][2]='renamed';s['files']['/proc/net/dev']=s['files']['/proc/net/dev'].replace('lan2:','renamed:')
        for suffix in ('of_node','device/driver'):s['links']['/sys/class/net/renamed/'+suffix]=s['links'].pop('/sys/class/net/lan2/'+suffix)
    case('interface_rename_uses_dt',rename,{'interface':'renamed'})
    def split_port(s):
        s['names'].append('extra');s['files']['/proc/net/dev']+='\n'+row('extra')
        s['links']['/sys/class/net/extra/of_node']='/sys/firmware/devicetree/base/soc/ethernet@1fb50000/ethernet@4/port@1'
        s['links']['/sys/class/net/extra/device/driver']='/drivers/airoha_eth'
    case('nbq_children_are_accumulated',split_port,{'tx':200})
    case('raw_register_parse_failure',lambda s:s.update(output=s['output'].replace('0x00000000','garbage',1)),{'error':True})
    case('partial_register_read',lambda s:s.update(output='0x00000000'),{'error':True})
    case('register_process_error',lambda s:s.update(status=1),{'error':True})
    case('wrong_board',lambda s:s['files'].update({'/tmp/sysinfo/board_name':'other'}),{'error':True})
    case('unsigned_register_decode',lambda s:s.update(output='\n'.join(['0xffffffff']*31)),{'raw':4294967295})
    mock=r'''
let state, reads, command;
function readfile(path) { if (path == '/proc/net/dev') reads++; return state.files[path]; }
function realpath(path) { return state.links[path]; }
function glob(path) { return map(state.names, n => '/sys/class/net/'+n); }
function popen(cmd) { command=cmd; return { read: function() { return state.output; }, close: function() { return state.status; } }; }
function check(ok, message) { if (!ok) die(message); }
'''
    tests=r'''
let results=[];
for (let test in cases) {
    state=test.state;reads=0;command='';
    let out=collect(), expected=test.expected;
    check(reads==1,test.name+': netdev snapshot count');
    check(!match(command,/0x1fb5[012]6/),test.name+': destructive GDM MIB read');
    if (test.name!='wrong_board') check(length(split(command,'; '))==31,test.name+': fixed register command');
    if (expected.error) { check(out.error,test.name+': expected sample failure'); }
    else {
        check(!out.error,test.name+': '+(out.error ?? ''));
        check(out.sample_uptime==123.45,test.name+': monotonic time');
        check(length(out.pse_ports)==10,test.name+': ports');
        if (expected.raw) check(out.pse_ports[7].drops==expected.raw,test.name+': unsigned counter');
        if (expected.unavailable) {
            let g=out[expected.unavailable];check(!g.available && g.tx==null,test.name+': unavailable must not be zero');
        } else {
            check(out.gdm4.available,test.name+': GDM4 missing');
            check(out.gdm4.tx==(expected.tx ?? 100),test.name+': cumulative TX');
            check(out.gdm4.rx_drop==(expected.tx==200 ? 6 : 3),test.name+': RX drop source');
            check(out.gdm4.tx_drop==(expected.tx==200 ? 14 : 7),test.name+': TX drop source');
        }
        if (expected.interface) check(out.gdm4.interfaces[0]==expected.interface,test.name+': interface mapping');
    }
    push(results,{name:test.name,passed:true});
}
print(sprintf('%J\n',results));
'''
    return 'let cases='+json.dumps(cases)+';\n'+mock+source+tests

class FrameEngine(unittest.TestCase):
    def test_display_lifecycle(self):
        subprocess.run(['node',str(ROOT/'tests/frame_engine_display.cjs')],check=True)

    def test_backend_has_no_gdm_register_reads(self):
        source=(ROOT/'package/w1700k-custom/root/usr/libexec/w1700k-frame-engine').read_text()
        for address in ('0x1fb506','0x1fb516','0x1fb526'):
            self.assertNotIn(address,source)
        self.assertIn("readfile('/proc/net/dev')",source)
        self.assertIn('/of_node',source)

    @unittest.skipUnless(shutil.which('ucode'),'ucode interpreter required; also exercised on the target router')
    def test_backend_fixtures(self):
        r=subprocess.run(['ucode','-'],input=backend_program(),text=True,capture_output=True,check=True)
        self.assertTrue(all(row['passed'] for row in json.loads(r.stdout)))
