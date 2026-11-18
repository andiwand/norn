import { describe, expect, it } from 'vitest';
import { isQuick } from './control-icons';

describe('isQuick', () => {
	it('offers switches and choices with an icon under the video', () => {
		expect(isQuick({ kind: 'toggle', icon: 'moon', group: 'Light' })).toBe(true);
		expect(isQuick({ kind: 'select', icon: 'activity', group: 'Alarm' })).toBe(true);
	});
	it('keeps sliders, buttons, network settings and controls without an icon in the settings', () => {
		expect(isQuick({ kind: 'range', icon: 'sun', group: 'Image' })).toBe(false);
		expect(isQuick({ kind: 'button', icon: 'siren', group: 'Alarm' })).toBe(false);
		expect(isQuick({ kind: 'toggle', icon: 'moon', group: 'Network' })).toBe(false);
		expect(isQuick({ kind: 'toggle', icon: null, group: 'Light' })).toBe(false);
	});
});
