 


更改 services/modbus.py  services/data.py


改一下功能， 

data.py 里增加一个  synch 的全局变量， 
内部结构类似：

synch: [
{
type: modbus,
action: read,
address: 0,
name: m1, 
value: 0, 
state: 0, // 0 初始值， 1 已同步
}, 
{
type: modbus,
action: read,
address: 1,
name: m2, 
value:1,
}, 
{
type: modbus,
action: write,
address: 10,
name: m1_, 
value: 0,
state: 0, // 0  未同步，初始值； 1 被写入新值， 尚未同步到设备 ， 2 已同步到设备
}, 
]

modbus.py ， 基于 datas/modbus.json 去初始化变量，运行的时候， 会修改 data.py 里的 synch 变量， 把 read 得到的值， 写入到 synch 里的 read , 然后 runtime 运行时， 可以  G2.readData(name) 来读取变量

在 runtime 运行的时候， 会通过 G2.setData(name,value) 来修改 synch 里的 write 类的 value ， 

modbus.py 运行时， 会周期性的扫描 synch 变量， 把 state 为 1 的 write 类的变量， 写入到 modbus 设备里， 并把 state 改为 2 。

增加  s7.py , 它会去周期性扫描 西门子 S7 设备的值， 操作逻辑跟 modbus 设备类似， 基于 datas/s7.json  里的配置

minth 里增加 setData 和  readData 方法， 删除  modbus.read 和  modbus.set 功能