// camera-view.js
// 相机视图：4 个相机画面 + 计算结果 + 底部控制栏

import { mqttClient } from './mqtt-client.js';

export default {
    name: 'CameraView',
    template: `
    <div class="cv-panel">
        <!-- 5 个相机画面（含计算结果） -->
        <div class="cv-camera-area">
            <div class="camera-grid">
                <div class="camera-cell" v-for="cam in cameras" :key="cam.key">
                    <div class="camera-title">{{ cam.name }}</div>
                    <img v-if="images[cam.key]" :src="'data:image/jpeg;base64,' + images[cam.key]" class="camera-img" />
                    <div v-else class="camera-placeholder">等待画面...</div>
                </div>

                <!-- 计算结果 -->
                <div class="camera-cell cv-result-cell">
                    <div class="camera-title">计算结果</div>
                    <img v-if="resultImage" :src="resultImageSrc" class="camera-img" />
                    <div v-else class="camera-placeholder">等待检测结果...</div>
                    <div v-if="resultText" class="cv-result-text">{{ resultText }}</div>
                </div>
            </div>
        </div>

        <!-- 底部控制栏 -->
        <div class="cv-bar">
            <div class="cv-bar-left">
                <button class="cv-btn cv-btn-on" :class="{active: streaming}" @click="startStream" :disabled="streaming">开启</button>
                <button class="cv-btn cv-btn-off" :class="{active: !streaming}" @click="stopStream" :disabled="!streaming">关闭</button>
                <button class="cv-btn cv-btn-save" @click="saveImage">拍摄</button>
            </div>
            <div class="cv-bar-center">
                <span v-if="streaming" class="cv-status cv-status-live">● 采集中</span>
                <span v-else class="cv-status">已停止</span>
            </div>
        </div>
    </div>
    `,
    data() {
        return {
            streaming: false,
            images: {},
            resultImage: null,
            resultText: '',
            cameras: [
                { key: 'head_color', name: '头部RGB' },
                { key: 'head_depth', name: '头部深度' },
                { key: 'left_wrist', name: '左手腕' },
                { key: 'right_wrist', name: '右手腕' },
            ],
            _onCamera: null,
            _onDetect: null
        };
    },
    computed: {
        resultImageSrc() {
            if (!this.resultImage) return '';
            const b64 = this.resultImage;
            if (b64.startsWith('iVBOR')) return 'data:image/png;base64,' + b64;
            if (b64.startsWith('/9j/'))  return 'data:image/jpeg;base64,' + b64;
            return 'data:image/jpeg;base64,' + b64;
        }
    },
    mounted() {
        this._onCamera = (data) => {
            if (!data) return;
            for (const cam of this.cameras) {
                if (data[cam.key]) {
                    this.images[cam.key] = data[cam.key];
                }
            }
        };
        mqttClient.addCameraCallback(this._onCamera);

        this._onDetect = (data) => {
            if (!data) return;
            if (data.image) {
                this.resultImage = data.image;
                this.resultText = data.timestamp || '';
            }
        };
        mqttClient.addCameraDetectCallback(this._onDetect);
    },
    beforeUnmount() {
        if (this._onCamera) {
            mqttClient.removeCameraCallback(this._onCamera);
        }
        if (this._onDetect) {
            mqttClient.removeCameraDetectCallback(this._onDetect);
        }
        if (this.streaming) {
            mqttClient.publishCameraControl('stop');
        }
    },
    methods: {
        startStream() {
            this.streaming = true;
            mqttClient.publishCameraControl('start');
        },
        stopStream() {
            this.streaming = false;
            mqttClient.publishCameraControl('stop');
        },
        saveImage() {
            mqttClient.publishCameraCommand('save', { cameras: ['kHeadColor', 'kHeadDepth'] });
        }
    }
};
