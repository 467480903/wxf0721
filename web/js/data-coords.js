// data-coords.js
// 坐标点位数据管理页面：读取、更新、删除
// 只处理 positions 数据，不处理关节和地图点位

import { mqttClient } from './mqtt-client.js';

export default {
    name: 'DataCoords',
    inject: ['getRobotStatus'],
    template: `
    <div class="panel djc-panel">
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
                        <td>坐标</td>
                        <td>{{ item.type }}</td>
                        <td>{{ item.name }}</td>
                        <td class="djc-summary">{{ summarize(item) }}</td>
                    </tr>
                </tbody>
            </table>
        </div>

        <div v-else class="djc-empty">
            点击右下角「读取」加载坐标点位数据
        </div>

        <!-- 底部固定操作栏 -->
        <div class="djc-actionbar">
            <div class="djc-left-info">
                <span v-if="items.length > 0" class="djc-count-bar">共 {{ items.length }} 条</span>
                <span v-if="selectedItem" class="djc-sel-info">
                    选中: 坐标 · {{ selectedItem.type }} · {{ selectedItem.name }}
                </span>
            </div>
            <div class="djc-actions">
                <button class="djc-btn djc-btn-read" @click="readData">读取</button>
                <button class="djc-btn djc-btn-go" :disabled="!selectedItem" @click="confirmGoTo">到位</button>
                <button class="djc-btn djc-btn-update" :disabled="!selectedItem" @click="confirmUpdate">更新</button>
                <button class="djc-btn djc-btn-delete" :disabled="!selectedItem" @click="confirmDelete">删除</button>
            </div>
        </div>

        <!-- 确认弹窗 -->
        <div v-if="confirmDialog.visible" class="djc-overlay" @click.self="cancelConfirm">
            <div class="djc-dialog">
                <div class="djc-dialog-header">
                    <span :class="['djc-dialog-icon', confirmDialog.iconClass]">{{ confirmDialog.icon }}</span>
                    <span class="djc-dialog-title">{{ confirmDialog.title }}</span>
                </div>
                <div class="djc-dialog-body">
                    {{ confirmDialog.message }}
                </div>
                <div class="djc-dialog-footer">
                    <button class="djc-btn djc-btn-cancel" @click="cancelConfirm">取消</button>
                    <button :class="['djc-btn', confirmDialog.confirmClass]" @click="executeConfirm">确定</button>
                </div>
            </div>
        </div>
    </div>
    `,
    data() {
        return {
            items: [],          // 只保留 category === 'positions' 的条目
            selectedIdx: -1,
            confirmDialog: {
                visible: false,
                title: '',
                message: '',
                icon: '',
                iconClass: '',
                confirmClass: '',
                action: null,
            },
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
            console.log('[坐标数据] 已请求读取');
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
            if (data && data.command === 'response' && Array.isArray(data.data)) {
                // 只保留坐标点位数据
                this.items = data.data.filter(it => it.category === 'positions');
                this.selectedIdx = -1;
                console.log('[坐标数据] 收到', this.items.length, '条数据');
            }
        },
        showConfirm(title, message, icon, iconClass, confirmClass, action) {
            this.confirmDialog = {
                visible: true,
                title,
                message,
                icon,
                iconClass,
                confirmClass,
                action,
            };
        },
        cancelConfirm() {
            this.confirmDialog.visible = false;
            this.confirmDialog.action = null;
        },
        executeConfirm() {
            if (this.confirmDialog.action) {
                this.confirmDialog.action();
            }
            this.cancelConfirm();
        },
        confirmGoTo() {
            const item = this.selectedItem;
            if (!item) return;
            this.showConfirm(
                '确认到位',
                `确定要让机器人运动到坐标「${item.type}/${item.name}」吗？请确保周围环境安全。`,
                '▶',
                'djc-icon-go',
                'djc-btn-go',
                () => this.doGoTo()
            );
        },
        doGoTo() {
            const item = this.selectedItem;
            if (!item) return;
            // 坐标运动服务端尚未实现
            console.log('[坐标数据] 坐标运动尚未实现', item.type, item.name);
            alert('坐标运动服务端尚未实现');
        },
        confirmUpdate() {
            const item = this.selectedItem;
            if (!item) return;
            this.showConfirm(
                '确认更新',
                `确定要用当前机器人末端位姿更新坐标「${item.type}/${item.name}」吗？原有数据将被覆盖。`,
                '↻',
                'djc-icon-update',
                'djc-btn-update',
                () => this.doUpdate()
            );
        },
        doUpdate() {
            const item = this.selectedItem;
            if (!item) return;
            // TODO: 末端位姿获取尚未接入，暂不支持
            console.log('[坐标数据] 坐标更新尚未实现', item.type, item.name);
            alert('坐标更新服务端尚未实现');
        },
        confirmDelete() {
            const item = this.selectedItem;
            if (!item) return;
            this.showConfirm(
                '确认删除',
                `确定要删除坐标「${item.type}/${item.name}」吗？此操作不可恢复。`,
                '✕',
                'djc-icon-delete',
                'djc-btn-delete',
                () => this.doDelete()
            );
        },
        doDelete() {
            const item = this.selectedItem;
            if (!item) return;
            mqttClient.publishDataReq('delete', {
                category: 'positions',
                type: item.type,
                name: item.name
            });
            this.items.splice(this.selectedIdx, 1);
            this.selectedIdx = -1;
            console.log('[坐标数据] 删除', item.type, item.name);
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
