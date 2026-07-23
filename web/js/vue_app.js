// vue_app.js
// 主 Vue 应用入口

import { createApp } from 'vue';
import { UrdfViewer } from './urdf-viewer.js';
import { mqttClient } from './mqtt-client.js';
import TeachJoints     from './teach-joints.js';
import TeachCoords     from './teach-coords.js';
import ProgramView     from './program-view.js';
import MapView         from './map-view.js';
import CameraView      from './camera-view.js';
import DataCollection  from './data-collection.js';
import ModelInference  from './model-inference.js';
import DataJointsCoords from './data-joints-coords.js';
import ChassisControl  from './chassis-control.js';
import PlaceholderView from './placeholder-view.js';


const App = {
    data() {
        return {
            currentMenu: '',          // 当前选中的菜单项 id
            openDropdown: '',         // 当前展开的下拉父菜单 id
            menus: [
                {
                    id: 'teach', label: '示教', icon: '🎮', children: [
                        { id: 'teach_joints', label: '角度轴' },
                        { id: 'teach_coords', label: '末端坐标' },
                    ]
                },
                {
                    id: 'data', label: '数据', icon: '📊', children: [
                        { id: 'data_jc',      label: '关节/坐标' },
                        { id: 'data_modbus',  label: 'modbus变量' },
                        { id: 'data_sync',    label: '同步' },
                        { id: 'data_mappoint',label: '地图点' },
                    ]
                },
                { id: 'program', label: '程序', icon: '📋' },
                {
                    id: 'map', label: '地图', icon: '🗺️', children: [
                        { id: 'map_scan',    label: '扫图建图' },
                        { id: 'map_use',     label: '使用地图' },
                        { id: 'map_chassis', label: '底盘控制' },
                    ]
                },
                {
                    id: 'camera', label: '相机', icon: '📷', children: [
                        { id: 'cam_capture', label: '采集' },
                        { id: 'cam_label',   label: '自动标注' },
                        { id: 'cam_flow',    label: '流程' },
                        { id: 'cam_settings',label: '设置' },
                    ]
                },
            ],
            urdfViewer: null,
            robotStatus: null   // 共享的机器人状态
        };
    },
    components: { TeachJoints, TeachCoords, ProgramView, MapView, CameraView, DataCollection, ModelInference, DataJointsCoords, ChassisControl, PlaceholderView },
    provide() {
        return {
            getUrdfViewer: () => this.urdfViewer,
            getRobotStatus: () => this.robotStatus
        };
    },
    computed: {
        // 当前菜单项的标题（用于占位组件）
        currentTitle() {
            for (const m of this.menus) {
                if (m.id === this.currentMenu) return m.label;
                if (m.children) {
                    const child = m.children.find(c => c.id === this.currentMenu);
                    if (child) return child.label;
                }
            }
            return '';
        },
        // 导航栏右侧显示的页面标题
        navPageTitle() {
            const titles = {
                'data_jc': '关节 / 坐标数据',
                'program': '程序 - main.py',
            };
            return titles[this.currentMenu] || '';
        },
        // 判断当前菜单是否为占位页面（非已实现的组件）
        isPlaceholder() {
            const implemented = [
                'teach_joints', 'teach_coords', 'program',
                'map_scan', 'map_chassis', 'cam_capture', 'data_jc'
            ];
            return this.currentMenu && !implemented.includes(this.currentMenu);
        }
    },
    template: `
    <div @click="closeDropdown">
        <canvas id="bg-canvas" ref="bgCanvas"></canvas>

        <nav id="toolbar" @click.stop>
            <span class="brand" @click="toggleHome">
                <span class="brand-logo"><img src="minth-logo.png" alt="Minth" /></span>
                底盘机器人
            </span>

            <template v-for="m in menus" :key="m.id">
                <!-- 无子菜单：直接按钮 -->
                <button v-if="!m.children"
                        class="menu-btn"
                        :class="{ active: currentMenu === m.id }"
                        @click="selectMenu(m.id)">
                    <span class="menu-icon">{{ m.icon }}</span>{{ m.label }}
                </button>

                <!-- 有子菜单：下拉 -->
                <div v-else class="menu-dropdown">
                    <button class="menu-btn"
                            :class="{ active: openDropdown === m.id || isChildActive(m) }"
                            @click="toggleDropdown(m.id)">
                        <span class="menu-icon">{{ m.icon }}</span>{{ m.label }}
                        <span class="dropdown-arrow">▾</span>
                    </button>
                    <div v-show="openDropdown === m.id" class="dropdown-panel">
                        <button v-for="c in m.children" :key="c.id"
                                class="dropdown-item"
                                :class="{ active: currentMenu === c.id }"
                                @click="selectMenu(c.id)">
                            {{ c.label }}
                        </button>
                    </div>
                </div>
            </template>

            <span class="nav-page-title" v-if="navPageTitle">{{ navPageTitle }}</span>
        </nav>

        <main id="content" :class="{ 'content-hidden': !currentMenu, 'content-fullscreen': currentMenu === 'map_chassis' || currentMenu === 'cam_capture' || currentMenu === 'data_jc' || currentMenu === 'program' }">
            <teach-joints     v-if="currentMenu === 'teach_joints'"></teach-joints>
            <teach-coords     v-if="currentMenu === 'teach_coords'"></teach-coords>
            <program-view     v-if="currentMenu === 'program'"></program-view>
            <map-view         v-if="currentMenu === 'map_scan'"></map-view>

            <!-- 地图 > 底盘控制 -->
            <chassis-control  v-if="currentMenu === 'map_chassis'"></chassis-control>

            <!-- 相机 > 采集 -->
            <camera-view      v-if="currentMenu === 'cam_capture'"></camera-view>

            <!-- 数据 > 关节/坐标 -->
            <data-joints-coords v-if="currentMenu === 'data_jc'"></data-joints-coords>

            <!-- 占位页面 -->
            <placeholder-view :title="currentTitle" v-if="isPlaceholder"></placeholder-view>
        </main>
    </div>
    `,
    methods: {
        selectMenu(id) {
            this.currentMenu = id;
            this.openDropdown = '';
        },
        toggleHome() {
            // 点击「底盘机器人」logo，收起所有功能页，显示 3D 模型
            this.currentMenu = '';
            this.openDropdown = '';
        },
        toggleDropdown(id) {
            this.openDropdown = this.openDropdown === id ? '' : id;
        },
        closeDropdown() {
            this.openDropdown = '';
        },
        isChildActive(menu) {
            if (!menu.children) return false;
            return menu.children.some(c => c.id === this.currentMenu);
        },
        toggleMenu(id) {
            this.currentMenu = this.currentMenu === id ? '' : id;
        },
        onStatus(data) {
            this.robotStatus = data;
            // 同步关节到 3D 模型
            if (data.joints && this.urdfViewer) {
                this.urdfViewer.setJointsFromStatus(data.joints);
            }
        }
    },
    mounted() {
        // 初始化背景 3D 模型
        this.urdfViewer = new UrdfViewer(this.$refs.bgCanvas);
        this.urdfViewer.loadUrdf('meshes/model.urdf');

        // 连接 MQTT，订阅机器人状态
        mqttClient.onStatus((data) => this.onStatus(data));
        mqttClient.connect();
    }
};

createApp(App).mount('#app');
