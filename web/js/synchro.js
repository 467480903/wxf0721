// synchro.js
// 同步数据视图：显示 Modbus + S7 两类设备的读写数据

import { mqttClient } from './mqtt-client.js';

export default {
    name: 'SynchroView',
    template: `
    <div class="panel mv-panel">
        <!-- 可滚动数据表格 -->
        <div class="mv-table-scroll" v-if="mergedRows.length > 0">
            <table class="mv-table">
                <thead>
                    <tr>
                        <th class="mv-col-type">读写类型</th>
                        <th class="mv-col-dev">设备名称</th>
                        <th class="mv-col-addr">地址</th>
                        <th class="mv-col-name">变量名称</th>
                        <th class="mv-col-val">当前值</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="row in mergedRows" :key="row.key"
                        :class="{ 'mv-row-selected': selectedRowKey === row.key }"
                        @click="selectRow(row)">
                        <td class="mv-type" :class="row.type === 'read' ? 'mv-type-read' : 'mv-type-write'">
                            {{ row.type === 'read' ? '读' : '写' }}
                        </td>
                        <td class="mv-dev">{{ row.deviceName || '--' }}</td>
                        <td class="mv-addr">{{ row.address !== null && row.address !== '' ? row.address : '--' }}</td>
                        <td class="mv-name">{{ row.name || '--' }}</td>
                        <td class="mv-val" :class="{ 'mv-null': row.value === null }">
                            {{ row.value === null ? '--' : row.value }}
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>

        <div v-else class="mv-no-device">暂无同步数据</div>

        <!-- 底部固定操作栏 -->
        <div class="mv-actionbar">
            <div class="mv-left-info">
                <span v-if="mergedRows.length > 0" class="mv-count-bar">共 {{ mergedRows.length }} 条</span>
                <span v-if="selectedRow" class="mv-sel-info">
                    选中: {{ selectedRow.type === 'read' ? '读' : '写' }} · {{ selectedRow.deviceName }} · {{ selectedRow.name }}
                </span>
            </div>
            <div class="mv-actions">
                <button class="mv-btn mv-btn-read" @click="refreshData">刷新</button>
                <button class="mv-btn mv-btn-edit" :disabled="!canEdit" @click="openEditDialog">修改</button>
            </div>
        </div>

        <!-- 修改值弹窗 -->
        <div v-if="editDialog.visible" class="save-overlay" @click.self="closeEditDialog">
            <div class="save-dialog" style="width:380px;">
                <h6 style="color:#e6a23c; margin-bottom:16px;">✏️ 修改变量</h6>
                <div class="mv-edit-form">
                    <div class="mv-form-row">
                        <label>设备</label>
                        <span class="mv-form-val">{{ editDialog.deviceName }}</span>
                    </div>
                    <div class="mv-form-row">
                        <label>地址</label>
                        <span class="mv-form-val">{{ editDialog.address }}</span>
                    </div>
                    <div class="mv-form-row">
                        <label>变量名称</label>
                        <span class="mv-form-val">{{ editDialog.name }}</span>
                    </div>
                    <div class="mv-form-row">
                        <label>当前值</label>
                        <span class="mv-form-val">{{ editDialog.oldValue === null ? '--' : editDialog.oldValue }}</span>
                    </div>
                    <div class="mv-form-row">
                        <label>新值</label>
                        <input class="mv-input" type="number"
                               v-model="editDialog.newValue"
                               placeholder="输入新值"
                               @keyup.enter="submitEdit" />
                    </div>
                </div>
                <div class="step-actions">
                    <button class="nav-btn" @click="closeEditDialog">取消</button>
                    <button class="nav-btn" style="background:#e6a23c; color:#fff;" @click="submitEdit">写入</button>
                </div>
            </div>
        </div>
    </div>
    `,
    data() {
        return {
            // 设备字典：key = "ip:port" (modbus) 或 "ip" (S7 无 port)
            devices: {},
            selectedRowKey: null,
            connected: false,
            editDialog: {
                visible: false,
                ip: '',
                port: '',
                deviceName: '',
                address: '',
                name: '',
                protocol: '',    // 'modbus' | 's7'
                oldValue: null,
                newValue: ''
            }
        };
    },
    computed: {
        deviceList() {
            return Object.values(this.devices);
        },
        selectedRow() {
            if (this.selectedRowKey === null) return null;
            return this.mergedRows.find(r => r.key === this.selectedRowKey) || null;
        },
        canEdit() {
            const row = this.selectedRow;
            return row && row.type === 'write';
        },
        mergedRows() {
            const rows = [];
            for (const dev of this.deviceList) {
                const devName = dev.type || '';
                // 读取区
                if (Array.isArray(dev.read)) {
                    for (const item of dev.read) {
                        rows.push({
                            key: `read:${dev.key}:${item.address !== undefined ? item.address : (item.addr ?? item.name)}`,
                            type: 'read',
                            deviceName: devName,
                            ip: dev.ip,
                            port: dev.port,
                            protocol: dev.protocol,
                            address: item.address !== undefined ? item.address : (item.addr || ''),
                            name: item.name || '',
                            value: item.value
                        });
                    }
                }
                // 写入区
                if (Array.isArray(dev.write)) {
                    for (const item of dev.write) {
                        rows.push({
                            key: `write:${dev.key}:${item.address !== undefined ? item.address : (item.addr || item.name)}`,
                            type: 'write',
                            deviceName: devName,
                            ip: dev.ip,
                            port: dev.port,
                            protocol: dev.protocol,
                            address: item.address !== undefined ? item.address : (item.addr || ''),
                            name: item.name || '',
                            value: item.value
                        });
                    }
                }
            }
            return rows;
        }
    },
    methods: {
        onModbusData(data) {
            if (!data || !Array.isArray(data.devices)) return;
            this.connected = true;

            for (const dev of data.devices) {
                const isS7 = data.command === 's7_data';
                // S7 没有 port 字段，用 ip 做 key；Modbus 用 ip:port
                const key = isS7 ? `s7:${dev.ip}` : `${dev.ip}:${dev.port}`;

                if (!this.devices[key]) {
                    this.devices[key] = {
                        key,
                        ip: dev.ip,
                        port: dev.port || '',
                        type: dev.name || '',
                        protocol: isS7 ? 's7' : 'modbus',
                        read: [],
                        write: []
                    };
                }
                if (dev.name) {
                    this.devices[key].type = dev.name;
                }
                if (isS7) {
                    // S7 数据格式: {addr, name, value}
                    if (Array.isArray(dev.read)) {
                        this.devices[key].read = dev.read.map(item => ({
                            address: item.addr || '',
                            name: item.name || '',
                            value: item.value
                        }));
                    }
                    if (Array.isArray(dev.write)) {
                        this.devices[key].write = dev.write.map(item => ({
                            address: item.addr || '',
                            name: item.name || '',
                            value: item.value
                        }));
                    }
                } else {
                    // Modbus 数据格式: {address, name, value}
                    if (Array.isArray(dev.read)) {
                        this.devices[key].read = dev.read;
                    }
                    if (Array.isArray(dev.write)) {
                        this.devices[key].write = dev.write;
                    }
                }
            }
        },
        selectRow(row) {
            this.selectedRowKey = this.selectedRowKey === row.key ? null : row.key;
        },
        refreshData() {
            mqttClient.publishModbusControl('read');
            console.log('[同步] 已请求刷新');
        },

        // ── 修改值 ──
        openEditDialog() {
            const row = this.selectedRow;
            if (!row || row.type !== 'write') return;
            this.editDialog = {
                visible: true,
                ip: row.ip,
                port: row.port,
                deviceName: row.deviceName,
                address: row.address,
                name: row.name,
                protocol: row.protocol,
                oldValue: row.value,
                newValue: row.value === null ? '' : String(row.value)
            };
        },
        closeEditDialog() {
            this.editDialog.visible = false;
        },
        submitEdit() {
            const val = parseInt(this.editDialog.newValue, 10);
            if (isNaN(val) || val < 0 || val > 65535) {
                alert('请输入 0-65535 之间的整数');
                return;
            }
            if (this.editDialog.protocol === 's7') {
                // S7 写入：使用 name 标识变量
                mqttClient.publishModbusControl('write', {
                    name: this.editDialog.name,
                    value: val
                });
            } else {
                // Modbus 写入：使用 ip + address
                mqttClient.publishModbusControl('write', {
                    ip: this.editDialog.ip,
                    address: parseInt(this.editDialog.address, 10),
                    value: val
                });
            }
            this.editDialog.visible = false;
            // 写入后稍等再刷新，确保读到最新值
            setTimeout(() => mqttClient.publishModbusControl('read'), 500);
        }
    },
    mounted() {
        mqttClient.addModbusDataCallback(this.onModbusData);
        mqttClient.publishModbusControl('read');
    },
    beforeUnmount() {
        mqttClient.removeModbusDataCallback(this.onModbusData);
    }
};
