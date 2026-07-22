// data-joints-coords.js
// 关节/坐标数据管理页面：读取、到位、更新、删除

import { mqttClient } from './mqtt-client.js';

export default {
    name: 'DataJointsCoords',
    inject: ['getRobotStatus'],
    template: `
    <div class="panel djc-panel">
        <h5 class="djc-title">关节 / 坐标数据</h5>

        <div class="djc-toolbar">
            <button class="djc-btn djc-btn-read" @click="readData">读取</button>
            <span class="djc-count" v-if="items.length > 0">共 {{ items.length }} 条</span>
        </div>

        <div class="djc-table-wrap" v-if="items.length > 0">
            <table class="djc-table">
                <thead>
                    <tr>
                        <th>分类</th>
                        <th>类型</th>
                        <th>名称</th>
                        <th>数据摘要</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="(item, idx) in items" :key="idx"
                        :class="{ 'djc-row-selected': selectedIdx === idx }"
                        @click="selectRow(idx)">
                        <td>{{ item.category === 'joints' ? '关节' : '坐标' }}</td>
                        <td>{{ item.type }}</td>
                        <td>{{ item.name }}</td>
                        <td class="djc-summary">{{ summarize(item) }}</td>
                    </tr>
                </tbody>
            </table>
        </div>

        <div v-else class="djc-empty">
            点击「读取」加载数据
        </div>

        <!-- 操作按钮栏 -->
        <div class="djc-actionbar" v-if="selectedItem">
            <span class="djc-sel-info">
                选中: {{ selectedItem.category === 'joints' ? '关节' : '坐标' }} ·
                {{ selectedItem.type }} · {{ selectedItem.name }}
            </span>
            <div class="djc-actions">
                <button class="djc-btn djc-btn-go" @click="goTo">到位</button>
                <button class="djc-btn djc-btn-update" @click="updateData">更新</button>
                <button class="djc-btn djc-btn-delete" @click="deleteData">删除</button>
            </div>
        </div>
    </div>
    `,
    data() {
        return {
            items: [],
            selectedIdx: -1,
        };
    },
    computed: {
        selectedItem() {
            return this.selectedIdx >= 0 ? this.items[this.selectedIdx] : null;
        }
    },
    methods: {
        readData() {
            mqttClient.publishDataReq('read');
            console.log('[数据] 已请求读取');
        },
        selectRow(idx) {
            this.selectedIdx = this.selectedIdx === idx ? -1 : idx;
        },
        summarize(item) {
            const v = item.value;
            if (!v) return '-';
            if (typeof v === 'object') {
                const keys = Object.keys(v);
                return `${keys.length} 项: ${keys.slice(0, 3).join(', ')}${keys.length > 3 ? '...' : ''}`;
            }
            return String(v);
        },
        onDataResp(data) {
            if (data && data.cmd === 'response' && Array.isArray(data.data)) {
                this.items = data.data;
                this.selectedIdx = -1;
                console.log('[数据] 收到', this.items.length, '条数据');
            }
        },
        goTo() {
            const item = this.selectedItem;
            if (!item) return;
            if (item.category === 'joints') {
                // 关节运动：发送 {cmd: type, data: name} 到 /G2_minth_app
                mqttClient.publishCommand(item.type, item.name);
                console.log('[到位] 关节', item.type, item.name);
            } else {
                // 坐标运动：尚未实现
                console.log('[到位] 坐标运动尚未实现', item.type, item.name);
                alert('坐标运动服务端尚未实现');
            }
        },
        updateData() {
            const item = this.selectedItem;
            if (!item) return;
            // 从全局 robotStatus 获取当前关节值
            const status = this.getRobotStatus();
            if (!status || !status.joints) {
                alert('未收到机器人状态数据');
                return;
            }
            // 根据类型过滤关节
            const joints = status.joints;
            const typeJointKeys = {
                WBC:   null,  // 全部
                arms:  ['idx21_arm_l_joint1','idx22_arm_l_joint2','idx23_arm_l_joint3','idx24_arm_l_joint4','idx25_arm_l_joint5','idx26_arm_l_joint6','idx27_arm_l_joint7',
                        'idx61_arm_r_joint1','idx62_arm_r_joint2','idx63_arm_r_joint3','idx64_arm_r_joint4','idx65_arm_r_joint5','idx66_arm_r_joint6','idx67_arm_r_joint7'],
                left:  ['idx21_arm_l_joint1','idx22_arm_l_joint2','idx23_arm_l_joint3','idx24_arm_l_joint4','idx25_arm_l_joint5','idx26_arm_l_joint6','idx27_arm_l_joint7'],
                right: ['idx61_arm_r_joint1','idx62_arm_r_joint2','idx63_arm_r_joint3','idx64_arm_r_joint4','idx65_arm_r_joint5','idx66_arm_r_joint6','idx67_arm_r_joint7'],
                head:  ['idx11_head_joint1','idx12_head_joint2','idx13_head_joint3'],
                waist: ['idx03_body_joint3','idx04_body_joint4','idx05_body_joint5','idx01_body_joint1','idx02_body_joint2'],
            };
            let dataToSend;
            if (item.category === 'joints') {
                const keys = typeJointKeys[item.type];
                if (keys === null) {
                    // WBC：全部关节
                    dataToSend = { ...joints };
                } else {
                    dataToSend = {};
                    keys.forEach(k => { if (joints[k] !== undefined) dataToSend[k] = joints[k]; });
                }
            } else {
                // 坐标更新：暂用空对象占位
                dataToSend = {};
            }
            mqttClient.publishDataReq('update', {
                category: item.category,
                type: item.type,
                name: item.name,
                data: dataToSend
            });
            // 更新本地数据
            item.value = dataToSend;
            console.log('[更新]', item.type, item.name, Object.keys(dataToSend).length, '项');
        },
        deleteData() {
            const item = this.selectedItem;
            if (!item) return;
            if (!confirm(`确认删除 ${item.type}/${item.name}？`)) return;
            mqttClient.publishDataReq('delete', {
                category: item.category,
                type: item.type,
                name: item.name
            });
            // 从本地列表移除
            this.items.splice(this.selectedIdx, 1);
            this.selectedIdx = -1;
            console.log('[删除]', item.type, item.name);
        }
    },
    mounted() {
        mqttClient.addDataRespCallback(this.onDataResp);
        // 自动读取一次
        this.readData();
    },
    beforeUnmount() {
        mqttClient.removeDataRespCallback(this.onDataResp);
    }
};
