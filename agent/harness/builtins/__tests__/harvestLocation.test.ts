import { describe, expect, it } from 'vitest';
import { findLocationFieldRef, isLocationFieldLine, locationCandidates, showsLocationRejected } from '../harvestLocation.js';

describe('findLocationFieldRef / isLocationFieldLine', () => {
  it('detects an English-labelled location field', () => {
    const snapshot = '- textbox "Location" [ref=e5]\n- searchbox "Keywords" [ref=e3]';
    expect(findLocationFieldRef(snapshot)).toBe('e5');
    expect(isLocationFieldLine('- textbox "Location" [ref=e5]')).toBe(true);
  });

  it('detects a German-labelled location field', () => {
    const snapshot = '- textbox "Ort" [ref=e9]\n- searchbox "Suchbegriff" [ref=e4]';
    expect(findLocationFieldRef(snapshot)).toBe('e9');
    expect(isLocationFieldLine('- textbox "Ort" [ref=e9]')).toBe(true);
  });

  it('ignores a plain keyword box', () => {
    const snapshot = '- searchbox "Search jobs" [ref=e3]';
    expect(findLocationFieldRef(snapshot)).toBeUndefined();
    expect(isLocationFieldLine('- searchbox "Search jobs" [ref=e3]')).toBe(false);
  });

  it('returns undefined when no field line matches at all', () => {
    expect(findLocationFieldRef('no fields here')).toBeUndefined();
  });

  it('detects an English "Where" label', () => {
    expect(isLocationFieldLine('- textbox "Where" [ref=e5]')).toBe(true);
  });

  it('detects a German "Wo" label', () => {
    expect(isLocationFieldLine('- textbox "Wo" [ref=e5]')).toBe(true);
  });
});

describe('locationCandidates', () => {
  it('expands a known alias in either direction', () => {
    expect(locationCandidates('Germany')).toEqual(['Germany', 'Deutschland']);
    expect(locationCandidates('Deutschland')).toEqual(['Deutschland', 'Germany']);
  });

  it('is case-insensitive when matching an alias pair', () => {
    expect(locationCandidates('germany')).toEqual(['germany', 'Deutschland']);
  });

  it('de-duplicates and caps at MAX_LOCATION_ATTEMPTS', () => {
    const candidates = locationCandidates('Germany');
    expect(candidates.length).toBeLessThanOrEqual(3);
    expect(new Set(candidates.map((c) => c.toLowerCase())).size).toBe(candidates.length);
  });

  it('returns just the original value when no alias is known', () => {
    expect(locationCandidates('Berlin')).toEqual(['Berlin']);
  });

  it('expands Munich to both München and Muenchen', () => {
    expect(locationCandidates('Munich')).toEqual(['Munich', 'München', 'Muenchen']);
  });

  it('maps München back to Munich', () => {
    expect(locationCandidates('München')).toEqual(['München', 'Munich']);
  });

  it('maps Muenchen back to Munich', () => {
    expect(locationCandidates('Muenchen')).toEqual(['Muenchen', 'Munich']);
  });

  it('expands Netherlands to include Niederlande', () => {
    expect(locationCandidates('Netherlands')).toContain('Niederlande');
  });
});

describe('showsLocationRejected', () => {
  it('matches known rejection phrases', () => {
    expect(showsLocationRejected('Sorry, location not found for that query')).toBe(true);
    expect(showsLocationRejected('We could not find that location, please try again')).toBe(true);
    expect(showsLocationRejected('Invalid location entered')).toBe(true);
  });

  it('does not match an ordinary page', () => {
    expect(showsLocationRejected('10 jobs found in Berlin')).toBe(false);
  });

  it('matches "did you mean" and German rejection phrases', () => {
    expect(showsLocationRejected('Did you mean Berlin?')).toBe(true);
    expect(showsLocationRejected('Meinten Sie Berlin?')).toBe(true);
    expect(showsLocationRejected('Ort nicht gefunden')).toBe(true);
    expect(showsLocationRejected('Unbekannter Ort')).toBe(true);
  });
});
