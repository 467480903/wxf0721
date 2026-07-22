// map-view.js
// 地图视图：基于激光雷达点云数据的 2D 地图（canvas 渲染）
// 通过 MQTT 订阅 /G2_minth_cloud 接收实时点云

import { mqttClient } from './mqtt-client.js';

export default {
    name: 'MapView',
    template: `
    <div class="panel">
        <h5>地图 - 激光雷达点云</h5>
        <canvas ref="canvas" class="map-canvas"></canvas>
        <div style="margin-top:10px; color:#888; font-size:13px;">
            总点数: {{ pointCount }} | 前: {{ frontCount }} | 后: {{ backCount }} | 缩放: {{ scale }}px/m
            <span style="margin-left:10px; color:#6f6;">● {{ connected ? '已连接' : '未连接' }}</span>
        </div>
    </div>
    `,
    data() {
        return {
            pointCount: 0,
            frontCount: 0,
            backCount: 0,
            centerX: 0,
            centerY: 0,
            scale: 40,       // 1 米 = 40 像素
            connected: false,
            points: [],       // [{x, y, z}]
            ctx: null,
            rafId: null,
            _onCloud: null
        };
    },
    mounted() {
        this.ctx = this.$refs.canvas.getContext('2d');
        this.resizeCanvas();
        window.addEventListener('resize', this.resizeCanvas);

        // 订阅点云数据
        this._onCloud = (data) => {
            this.connected = true;
            if (data && data.points) {
                this.points = data.points.map(p => ({ x: p[0], y: p[1], z: p[2] }));
                this.pointCount = this.points.length;
                this.frontCount = data.front_count || 0;
                this.backCount = data.back_count || 0;

                // 自动计算中心（取平均值）
                if (this.points.length > 0) {
                    let sx = 0, sy = 0;
                    for (const p of this.points) { sx += p.x; sy += p.y; }
                    this.centerX = sx / this.points.length;
                    this.centerY = sy / this.points.length;
                }
            }
        };

        // mqttClient 已连接 /G2_minth_status，这里复用同一个连接
        // 通过 onMessageArrived 分发，需要额外注册回调
        mqttClient.addCloudCallback(this._onCloud);

        // 通知后端开始发布点云
        mqttClient.publishCloudControl('start_cloud');

        this.render();
    },
    beforeUnmount() {
        window.removeEventListener('resize', this.resizeCanvas);
        cancelAnimationFrame(this.rafId);
        if (this._onCloud) {
            mqttClient.removeCloudCallback(this._onCloud);
        }
        // 通知后端停止发布点云
        mqttClient.publishCloudControl('stop_cloud');
    },
    methods: {
        resizeCanvas() {
            const c = this.$refs.canvas;
            const rect = c.getBoundingClientRect();
            c.width = rect.width;
            c.height = rect.height;
        },
        render() {
            const ctx = this.ctx;
            const c = this.$refs.canvas;
            if (!ctx) return;

            // 清屏
            ctx.fillStyle = '#0a0c10';
            ctx.fillRect(0, 0, c.width, c.height);

            const cx = c.width / 2;
            const cy = c.height / 2;
            const scale = this.scale;

            // 网格
            ctx.strokeStyle = '#1a1f28';
            ctx.lineWidth = 1;
            for (let x = cx % 50; x < c.width; x += 50) {
                ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, c.height); ctx.stroke();
            }
            for (let y = cy % 50; y < c.height; y += 50) {
                ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(c.width, y); ctx.stroke();
            }

            // 坐标轴
            ctx.strokeStyle = '#3a4452';
            ctx.lineWidth = 1;
            ctx.beginPath(); ctx.moveTo(0, cy); ctx.lineTo(c.width, cy); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(cx, 0); ctx.lineTo(cx, c.height); ctx.stroke();

            // 绘制点云
            ctx.fillStyle = '#6cf';
            for (const p of this.points) {
                const x = cx + (p.x - this.centerX) * scale;
                const y = cy - (p.y - this.centerY) * scale;
                if (x >= 0 && x < c.width && y >= 0 && y < c.height) {
                    ctx.fillRect(x - 0.5, y - 0.5, 1.5, 1.5);
                }
            }

            // 机器人位置（中心）
            ctx.fillStyle = '#0f0';
            ctx.beginPath();
            ctx.arc(cx, cy, 5, 0, Math.PI * 2);
            ctx.fill();

            // 机器人朝向指示
            ctx.strokeStyle = '#0f0';
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.moveTo(cx, cy);
            ctx.lineTo(cx + 15, cy);
            ctx.stroke();

            this.rafId = requestAnimationFrame(this.render.bind(this));
        }
    }
};
