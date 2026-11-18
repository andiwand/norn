import { describe, expect, it } from 'vitest';
import { aKind, clipSources, setLabels, sourcesLabel, unconfirmed } from './format';

describe('who detected it', () => {
	it('says it in words', () => {
		expect(sourcesLabel(['camera', 'norn'])).toBe('camera + Norn');
		expect(sourcesLabel(undefined)).toBe('');
		expect(clipSources({ trigger: 'person', meta: { by: { person: ['norn'] } } })).toBe('Norn');
	});

	it("marks a camera's alarm that Norn's AI looked at and didn't see", () => {
		const camera = { by: { person: ['camera'] } };
		expect(unconfirmed({ trigger: 'person', meta: { ...camera, norn_saw: [] } })).toBe(true);
		expect(unconfirmed({ trigger: 'person', meta: { ...camera, norn_saw: ['animal'] } })).toBe(
			true
		);
		// Norn saw it, or saw it itself, or didn't look, or it isn't an object: no mark.
		expect(unconfirmed({ trigger: 'person', meta: { ...camera, norn_saw: ['person'] } })).toBe(
			false
		);
		expect(
			unconfirmed({ trigger: 'person', meta: { by: { person: ['camera', 'norn'] }, norn_saw: [] } })
		).toBe(false);
		expect(unconfirmed({ trigger: 'person', meta: camera })).toBe(false);
		expect(unconfirmed({ trigger: 'person', meta: { norn_saw: [] } })).toBe(false); // nobody noted
		expect(
			unconfirmed({ trigger: 'motion', meta: { by: { motion: ['camera'] }, norn_saw: [] } })
		).toBe(false);
	});

	it('names a kind in a sentence', () => {
		setLabels([
			{ id: 'animal', name: 'Animal' },
			{ id: 'person', name: 'Person' }
		]);
		expect(aKind('animal')).toBe('an animal');
		expect(aKind('person')).toBe('a person');
	});
});
