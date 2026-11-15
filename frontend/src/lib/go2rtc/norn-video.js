// @ts-nocheck -- extends the untyped vendored player
// <norn-video>: go2rtc's VideoRTC with Norn's defaults. It reports its state as DOM events,
// so the Svelte component draws the overlay instead of the player.
//
// Events: `norn-mode` (detail: 'webrtc' | 'mse' | 'hls' | 'mjpeg'), `norn-state`
// (detail: 'connecting' | 'playing' | 'error'), `norn-error` (detail: message).
import { VideoRTC } from './video-rtc.js';

class NornVideo extends VideoRTC {
	constructor() {
		super();
		// Norn runs on the local network, where host candidates connect; no public STUN needed.
		this.pcConfig = { ...this.pcConfig, iceServers: [] };
		this.visibilityThreshold = 0.05; // stop streams scrolled out of view
	}

	emit(type, detail) {
		this.dispatchEvent(new CustomEvent(type, { detail }));
	}

	oninit() {
		super.oninit();
		this.video.controls = false;
		this.video.muted = true;
		this.video.style.objectFit = this.getAttribute('fit') || 'contain';
		this.video.addEventListener('playing', () => this.emit('norn-state', 'playing'));
		this.video.addEventListener('waiting', () => this.emit('norn-state', 'connecting'));
	}

	onconnect() {
		const result = super.onconnect();
		if (result) this.emit('norn-state', 'connecting');
		return result;
	}

	onopen() {
		const result = super.onopen();
		this.onmessage['norn'] = (msg) => {
			if (msg.type === 'error') {
				this.emit('norn-error', msg.value);
				this.emit('norn-state', 'error');
			} else if (['mse', 'hls', 'mp4', 'mjpeg'].includes(msg.type)) {
				this.emit('norn-mode', msg.type);
			}
		};
		return result;
	}

	// MJPEG arrives as single JPEG frames. go2rtc's player sets them as the <video> poster, which
	// ignores object-fit; an <img> fills the tile like the video does.
	onmjpeg() {
		if (!this.image) {
			this.image = document.createElement('img');
			this.image.alt = '';
			Object.assign(this.image.style, {
				position: 'absolute',
				inset: '0',
				width: '100%',
				height: '100%',
				objectFit: this.getAttribute('fit') || 'contain'
			});
			this.style.position = 'relative';
			this.appendChild(this.image);
		}
		let first = true;
		this.ondata = (data) => {
			const url = URL.createObjectURL(new Blob([data], { type: 'image/jpeg' }));
			this.image.onload = () => URL.revokeObjectURL(url);
			this.image.src = url;
			if (first) {
				first = false;
				this.emit('norn-state', 'playing');
			}
		};
		this.send({ type: 'mjpeg' }); // ask go2rtc to start the frames
	}

	onpcvideo(video) {
		super.onpcvideo(video);
		if (this.pcState !== WebSocket.CLOSED) this.emit('norn-mode', 'webrtc');
		this.video.controls = false;
		this.video.style.objectFit = this.getAttribute('fit') || 'contain';
	}
}

if (!customElements.get('norn-video')) customElements.define('norn-video', NornVideo);
