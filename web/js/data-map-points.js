// data-map-points.js
// 「数据 > 地图点位」页面：读取 / 到位 / 更新 / 删除
// 只操作 robot_data.db 的 map_points 表，不读写 G2 机器人内部地图数据
//   - 读取：拉取 DB 全表
//   - 到位：按 DB 里的坐标直接导航（只运动，不改地图）
//   - 更新：编辑坐标/朝向后写回 DB
//   - 删除：从 DB 删除

import { mqttClient } from './mqtt-client.js';

export default {
    name: 'DataMapPoints',
    inject: ['isLoggedIn'],
    template: `
    <div class="panel djc-panel">
        <div class="djc-table-wrap" v-if="items.length > 0">
            <table class="djc-table">
                <thead>
                    <tr>
                        <th>名称</th>
                        <th>来源</th>
                        <th>位置 (x, y, z)</th>
                        <th>朝向四元数 (x, y, z, w)</th>
                    </tr>
                </thead>
                <tbody>
                    <tr v-for="(item, idx) in items" :key="idx"
                        :class="{ 'djc-row-selected': selectedIdx === idx }"
                        @click="selectRow(idx)">
                        <td>{{ item.name }}</td>
                        <td>{{ item.source }}</td>
                        <td class="djc-summary">{{ fmtPos(item.position) }}</td>
                        <td class="djc-summary">{{ fmtOri(item.orientation) }}</td>
                    </tr>
                </tbody>
            </table>
        </div>

        <div v-else class="djc-empty">
            点击右下角「读取」加载数据库点位
        </div>

        <!-- 底部固定操作栏 -->
        <div class="djc-actionbar">
            <div class="djc-left-info">
                <span v-if="items.length > 0" class="djc-count-bar">共 {{ items.length }} 条</span>
                <span v-if="gotoMsg" class="djc-sel-info">{{ gotoMsg }}</span>
                <span v-else-if="selectedItem" class="djc-sel-info">
                    选中: {{ selectedItem.name }} · {{ selectedItem.source }}
                </span>
            </div>
            <div class="djc-actions">
                <button class="djc-btn djc-btn-read" @click="readData">读取</button>
                <button class="djc-btn djc-btn-go" :disabled="!selectedItem || gotoBusy"
                        @click="confirmGoTo">{{ gotoBusy ? '导航中...' : '到位' }}</button>
                <button class="djc-btn djc-btn-update" :disabled="!selectedItem" @click="openUpdate">更新</button>
                <button class="djc-btn djc-btn-delete" :disabled="!selectedItem" @click="confirmDelete">删除</button>
            </div>
        </div>

        <!-- 更新编辑弹窗 -->
        <div v-if="editDialog.visible" class="djc-overlay" @click.self="editDialog.visible = false">
            <div class="djc-dialog">
                <div class="djc-dialog-header">
                    <span class="djc-dialog-icon">✏️</span>
                    <span class="djc-dialog-title">更新点位 — {{ editDialog.name }}</span>
                </div>
                <div class="djc-dialog-body">
                    <div class="dmp-edit-grid">
                        <label>x (m)</label><input type="number" step="0.001" v-model.number="editDialog.position[0]" />
                        <label>y (m)</label><input type="number" step="0.001" v-model.number="editDialog.position[1]" />
                        <label>z (m)</label><input type="number" step="0.001" v-model.number="editDialog.position[2]" />
                        <label>qx</label><input type="number" step="0.0001" v-model.number="editDialog.orientation[0]" />
                        <label>qy</label><input type="number" step="0.0001" v-model.number="editDialog.orientation[1]" />
                        <label>qz</label><input type="number" step="0.0001" v-model.number="editDialog.orientation[2]" />
                        <label>qw</label><input type="number" step="0.0001" v-model.number="editDialog.orientation[3]" />
                    </div>
                </div>
                <div class="djc-dialog-footer">
                    <button class="djc-btn djc-btn-cancel" @click="editDialog.visible = false">取消</button>
                    <button class="djc-btn djc-btn-save" @click="submitUpdate">保存</button>
                </div>
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
            items: [],
            selectedIdx: -1,
            gotoBusy: false,
            gotoMsg: '',
            editDialog: {
                visible: false,
                name: '',
                source: 'local',
                position: [0, 0, 0],
                orientation: [0, 0, 0, 1],
            },
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
        // ── 基础 ──────────────────────────────────────
        selectRow(idx) {
            this.selectedIdx = this.selectedIdx === idx ? -1 : idx;
            this.gotoMsg = '';
        },
        fmtPos(p) {
            if (!Array.isArray(p) || p.length < 2) return '-';
            return p.map(v => Number(v).toFixed(3)).join(', ');
        },
        fmtOri(o) {
            if (!Array.isArray(o) || o.length < 4) return '-';
            return o.map(v => Number(v).toFixed(3)).join(', ');
        },

        // ── 读取 ──────────────────────────────────────
        readData() {
            mqttClient.publishMapDbControl('read');
            console.log('[地图点位] 已请求读取 DB 点位');
        },
        onDataResp(data) {
            if (data && data.command === 'db_points' && Array.isArray(data.data)) {
                this.items = data.data;
                this.selectedIdx = -1;
                console.log('[地图点位] 收到', this.items.length, '条点位');
            } else if (data && data.command === 'goto_result' && data.data) {
                // 到位结果
                this.gotoBusy = false;
                const d = data.data;
                this.gotoMsg = d.success
                    ? `✓ ${d.name} 到位成功`
                    : `✗ ${d.name} ${d.message || '导航失败'}`;
                console.log('[地图点位] 到位结果:', d);
            }
        },

        // ── 更新 ──────────────────────────────────────
        openUpdate() {
            const it = this.selectedItem;
            if (!it) return;
            this.editDialog = {
                visible: true,
                name: it.name,
                source: it.source,
                position: [...(it.position || [0, 0, 0])],
                orientation: [...(it.orientation || [0, 0, 0, 1])],
            };
        },
        submitUpdate() {
            const d = this.editDialog;
            mqttClient.publishMapDbControl('update', {
                name: d.name,
                source: d.source,
                position: d.position.map(v => Number(v) || 0),
                orientation: d.orientation.map(v => Number(v) || 0),
            });
            d.visible = false;
            console.log('[地图点位] 已提交更新:', d.name);
        },

        // ── 到位 / 删除（确认弹窗）────────────────────
        showConfirm(title, message, icon, iconClass, confirmClass, action) {
            this.confirmDialog = { visible: true, title, message, icon, iconClass, confirmClass, action };
        },
        cancelConfirm() {
            this.confirmDialog.visible = false;
            this.confirmDialog.action = null;
        },
        executeConfirm() {
            if (this.confirmDialog.action) this.confirmDialog.action();
            this.cancelConfirm();
        },
        confirmGoTo() {
            const it = this.selectedItem;
            if (!it) return;
            this.showConfirm(
                '到位确认',
                `机器人将导航到点位「${it.name}」(${this.fmtPos(it.position)})，确认执行？`,
                '🚀', 'djc-icon-go', 'djc-btn-go',
                () => {
                    this.gotoBusy = true;
                    this.gotoMsg = `导航中: ${it.name}...`;
                    mqttClient.publishMapDbControl('goto', { name: it.name, source: it.source });
                    console.log('[地图点位] 已请求到位:', it.name);
                }
            );
        },
        confirmDelete() {
            const it = this.selectedItem;
            if (!it) return;
            this.showConfirm(
                '删除确认',
                `确定删除点位「${it.name}」？该操作只删除数据库记录，不影响机器人内部地图。`,
                '🗑️', 'djc-icon-danger', 'djc-btn-delete',
                () => {
                    // 只按名称删除
                    mqttClient.publishMapDbControl('delete', { name: it.name });
                    console.log('[地图点位] 已提交删除:', it.name);
                    // 删除后延时重新从数据库读取全表并刷新页面
                    setTimeout(() => this.readData(), 800);
                }
            );
        },
    },
    mounted() {
        this._cb = (data) => this.onDataResp(data);
        mqttClient.addMapDbDataCallback(this._cb);
        // 进入页面自动读取一次
        this.readData();
    },
    unmounted() {
        mqttClient.removeMapDbDataCallback(this._cb);
    }
};
