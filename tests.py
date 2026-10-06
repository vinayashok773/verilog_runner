import json, re, shutil, subprocess, unittest
from pathlib import Path
import server

def files(s): return [{'name':'design.sv','text':s}]

class Generation(unittest.TestCase):
    def test_parameters(self):
        a=server.analyze(files('module counter #(parameter W=8, parameter A=$clog2(W))(input clk, input signed [W-1:0] d, output reg [W-1:0] q); always @(posedge clk) q<=d; endmodule'))
        self.assertEqual(a['ports'][1]['width'],'[W-1:0]')
        self.assertTrue(a['ports'][1]['signed'])
        tb=server.make_tb(a,{'clk':{'role':'clock','initial':'0','period':9},'d':{'role':'sequence','initial':'0','sequence':"0:0, 12:8'hAA"}},91,{'W':'16'})
        self.assertIn('localparam W = 16;',tb)
        self.assertIn('forever #4.5 clk',tb)
        self.assertIn('#91; $finish;',tb)
        self.assertIn("#12 d = 8'hAA",tb)
    def test_nonansi(self):
        a=server.analyze(files('module m(a,b,q); input [7:0] a,b; output [7:0] q; assign q=a+b; endmodule'))
        self.assertEqual([p['name'] for p in a['ports']],['a','b','q'])
        self.assertEqual([p['width'] for p in a['ports']],['[7:0]']*3)
    def test_top(self):
        a=server.analyze(files('module helper(input x,output y); assign y=x; endmodule module top(input a,output b);helper u(a,b);endmodule'),'top')
        self.assertEqual(a['name'],'top')
    def test_stale_source(self):
        a=server.analyze(files('module m(input fresh, output q); assign q=fresh; endmodule'))
        self.assertIn('.fresh(fresh)',server.make_tb(a,{},20,{}))
    def test_multidimensional(self):
        a=server.analyze(files('module m(input [1:0][3:0] a,output [7:0] q); assign q=a; endmodule'))
        self.assertEqual(a['ports'][0]['width'],'[1:0] [3:0]')
    def test_rejections(self):
        for decl in ['inout bus','input logic [7:0] mem [0:3]','input my_type a']:
            with self.assertRaises(ValueError): server.analyze(files('module m('+decl+'); endmodule'))
        with self.assertRaises(ValueError): server.value('hello')
        with self.assertRaises(ValueError): server.validate_files([{'name':'../bad.v','text':''}])
    def test_absolute_sequences(self):
        a=server.analyze(files('module m(input a); endmodule'))
        tb=server.make_tb(a,{'a':{'role':'sequence','sequence':'0:0, 12:1, 22:0'}},30,{})
        self.assertIn('#12 a = 1;',tb); self.assertIn('#10 a = 0;',tb)
        with self.assertRaises(ValueError): server.make_tb(a,{'a':{'role':'sequence','sequence':'20:0, 10:1'}},30,{})

@unittest.skipUnless(shutil.which('iverilog') and shutil.which('vvp'),'Icarus unavailable; actual simulation checks not executed')
class Simulation(unittest.TestCase):
    def test_flipflop(self):
        src='module dff(input clk,input rst,input d,output reg q);always @(posedge clk or posedge rst) if(rst)q<=0;else q<=d;endmodule'
        tb='''`timescale 1ns/1ps
module tb;
reg clk=0,rst=1,d=0; wire q;
dff dut(clk,rst,d,q); always #5 clk=~clk;
initial begin $dumpfile("wave.vcd");$dumpvars(0,tb);
#2 rst=0; #10 d=1; #4;
if(q!==1) $fatal(1,"DFF mismatch");
#6 d=0; #4;if(q!==0)$fatal(1,"DFF mismatch");
$display("PASS_DFF");$finish;end endmodule'''
        r=server.run({'files':files(src),'mode':'custom','testbench':tb,'tbtop':'tb'})
        self.assertTrue(r['ok'],r['log']);self.assertIn('PASS_DFF',r['log']);self.assertIn('$enddefinitions',r['vcd'])
    def test_parameter_counter(self):
        src='module counter #(parameter W=12)(input clk,input reset,output reg [W-1:0] q);always @(posedge clk)if(reset)q<=0;else q<=q+1;endmodule'
        r=server.run({'files':files(src),'top':'counter','duration':91,'overrides':{'W':'16'},'config':{'clk':{'role':'clock','initial':'0','period':10},'reset':{'role':'reset','initial':'1','release':12}}})
        self.assertTrue(r['ok'],r['log']);self.assertRegex(r['vcd'],r'\$var\s+\w+\s+16\s');self.assertIn('#91000',r['vcd'])
    def test_multifile(self):
        fs=[{'name':'adder.sv','text':'module adder(input [7:0] a,b,output [7:0] y);assign y=a+b;endmodule'},{'name':'top.sv','text':'module top(input [7:0] a,b,output [7:0] q);adder u(a,b,q);endmodule'}]
        r=server.run({'files':fs,'top':'top','config':{'a':{'initial':'8'},'b':{'initial':'9'}},'duration':20})
        self.assertTrue(r['ok'],r['log']); self.assertIn('b10001',r['vcd'])
    def test_compile_error(self):
        r=server.run({'files':files('module m(input a,output q); assign q=; endmodule'),'duration':20})
        self.assertFalse(r['ok']);self.assertNotIn('vcd',r)

class Javascript(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'),'Node optional; browser-code check skipped')
    def test_js_and_vcd(self):
        html=(Path(__file__).parent/'index.html').read_text()
        js=re.search(r'<script>(.*?)</script>',html,re.S)[1]
        subprocess.run(['node','--check'],input=js,text=True,check=True,capture_output=True)
        parser=js[js.index('function parseVcd'):js.index('function renderSignals')]
        sample='$timescale 1 ns $end\n$scope module tb $end\n$var wire 1 ! q $end\n$var wire 8 " data [7:0] $end\n$upscope $end\n$enddefinitions $end\n$dumpvars\n0!\nb10101010 "\n$end\n#10\n1!\n#20\nx!'
        check=parser+'\nconst w=parseVcd('+json.dumps(sample)+');if(w.unit!=="1ns"||w.end!==20||w.signals.length!==2||w.events["!"].length!==3)throw Error("VCD parser regression");'
        subprocess.run(['node','-e',check],check=True,capture_output=True)

if __name__=='__main__': unittest.main(verbosity=2)
