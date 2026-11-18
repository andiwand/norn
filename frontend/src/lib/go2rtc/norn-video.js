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
		// go2rtc's own page and view watching can't be undone: this class watches instead (see watch).
		this.visibilityCheck = false;
		this.visibilityThreshold = 0;
	}

	// Pause when the page is hidden or the player is scrolled out of view (go2rtc's grace period
	// applies); removable, unlike go2rtc's, so a removed player leaves nothing behind.
	watch() {
		if (this.onvisibility) return;
		this.onvisibility = () => {
			if (document.hidden) this.disconnectedCallback();
			else if (this.isConnected) this.connectedCallback();
		};
		document.addEventListener('visibilitychange', this.onvisibility);
		this.observer = new IntersectionObserver(
			(entries) => {
				for (const entry of entries) {
					if (!entry.isIntersecting) this.disconnectedCallback();
					else if (this.isConnected) this.connectedCallback();
				}
			},
			{ threshold: 0.05 }
		);
		this.observer.observe(this);
	}

	unwatch() {
		document.removeEventListener('visibilitychange', this.onvisibility);
		this.observer?.disconnect();
		this.onvisibility = this.observer = null;
	}

	connectedCallback() {
		super.connectedCallback();
		this.watch();
	}

	disconnectedCallback() {
		// Hidden or out of view: go2rtc closes after a grace period.
		if (this.isConnected) return super.disconnectedCallback();
		// Removed from the page. A move (in a keyed list) is back before this runs; else close the
		// connection now, not after go2rtc's 5 seconds.
		queueMicrotask(() => {
			if (this.isConnected) return;
			this.unwatch();
			clearTimeout(this.disconnectTID);
			clearTimeout(this.reconnectTID);
			this.disconnectTID = this.reconnectTID = 0;
			if (this.video) this.ondisconnect();
			if (this.imageURL) URL.revokeObjectURL(this.imageURL);
			this.imageURL = null;
		});
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
			// The frame before is shown already (or never will be): its URL can go.
			if (this.imageURL) URL.revokeObjectURL(this.imageURL);
			this.imageURL = URL.createObjectURL(new Blob([data], { type: 'image/jpeg' }));
			this.image.src = this.imageURL;
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
