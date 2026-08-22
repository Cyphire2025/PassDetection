import { validateGoogleServicesDocument } from '../../../../scripts/validate-google-services';
import { findUnexpectedVulnerabilities } from '../../../../scripts/verify-runtime-audit';
import {
  parseAndroidFingerprints,
  validateAndroidAssetLinks,
  validateAppleAppSiteAssociation,
} from '../../../../scripts/validate-verified-links';

const fingerprint = Array.from({ length: 32 }, (_, index) =>
  index.toString(16).padStart(2, '0'),
).join(':').toUpperCase();

describe('release gates', () => {
  it('requires the production Android signing identity in assetlinks.json', () => {
    const fingerprints = parseAndroidFingerprints(fingerprint.toLowerCase());
    expect(() => parseAndroidFingerprints('not-a-sha256-fingerprint')).toThrow(
      'GC_ANDROID_APP_LINK_SHA256_CERT_FINGERPRINTS must contain',
    );
    expect(() => validateAndroidAssetLinks([
      {
        relation: ['delegate_permission/common.handle_all_urls'],
        target: {
          namespace: 'android_app',
          package_name: 'com.globalconnects.groupcompanion',
          sha256_cert_fingerprints: [fingerprint],
        },
      },
    ], fingerprints)).not.toThrow();

    expect(() => validateAndroidAssetLinks([], fingerprints)).toThrow(
      'has no handle_all_urls statement',
    );

    const unexpectedFingerprint = Array.from({ length: 32 }, (_, index) =>
      (255 - index).toString(16).padStart(2, '0'),
    ).join(':').toUpperCase();
    expect(() => validateAndroidAssetLinks([
      {
        relation: ['delegate_permission/common.handle_all_urls'],
        target: {
          namespace: 'android_app',
          package_name: 'com.globalconnects.groupcompanion',
          sha256_cert_fingerprints: [fingerprint, unexpectedFingerprint],
        },
      },
    ], fingerprints)).toThrow('contains 1 unexpected signing fingerprint');

    expect(() => validateAndroidAssetLinks([
      {
        relation: ['delegate_permission/common.handle_all_urls'],
        target: {
          namespace: 'android_app',
          package_name: 'com.globalconnects.groupcompanion',
          sha256_cert_fingerprints: [fingerprint],
        },
      },
      {
        relation: ['delegate_permission/common.handle_all_urls'],
        target: {
          namespace: 'android_app',
          package_name: 'com.attacker.clone',
          sha256_cert_fingerprints: [unexpectedFingerprint],
        },
      },
    ], fingerprints)).toThrow('delegates verified links to 1 unexpected package');
  });

  it('requires the production iOS app and /gc paths in the AASA document', () => {
    expect(() => validateAppleAppSiteAssociation({
      applinks: {
        details: [
          {
            appIDs: ['ABCDE12345.com.globalconnects.groupcompanion'],
            components: [{ '/': '/gc' }, { '/': '/gc/*' }],
          },
        ],
      },
    }, 'ABCDE12345')).not.toThrow();

    expect(() => validateAppleAppSiteAssociation({
      applinks: { details: [] },
    }, 'ABCDE12345')).toThrow('does not allow');

    expect(() => validateAppleAppSiteAssociation({
      applinks: {
        details: [
          {
            appIDs: ['ABCDE12345.com.globalconnects.groupcompanion'],
            components: [{ '/': '*' }],
          },
        ],
      },
    }, 'ABCDE12345')).toThrow('does not allow');

    expect(() => validateAppleAppSiteAssociation({
      applinks: {
        details: [
          {
            appIDs: ['ABCDE12345.com.globalconnects.groupcompanion'],
            components: [{ '/': '/gc' }, { '/': '/gc/*' }],
          },
          {
            appID: 'ABCDE12345.com.globalconnects.groupcompanion',
            paths: ['*'],
          },
        ],
      },
    }, 'ABCDE12345')).toThrow('does not allow');
  });

  it('rejects a Firebase file for a different Android package', () => {
    expect(() => validateGoogleServicesDocument({
      client: [
        {
          client_info: {
            android_client_info: { package_name: 'com.example.wrong' },
          },
        },
      ],
    })).toThrow('has no Android client');
  });

  it('rejects every high or critical dependency finding without exceptions', () => {
    const metroReport = {
      vulnerabilities: {
        metro: {
          severity: 'high',
          via: ['image-size'],
        },
        'image-size': {
          severity: 'high',
          via: [
            {
              url: 'https://github.com/advisories/GHSA-w3rx-r6r6-pgpr',
            },
          ],
        },
      },
    };
    expect(findUnexpectedVulnerabilities(metroReport)).toEqual([
      {
        name: 'metro',
        advisoryUrls: ['https://github.com/advisories/GHSA-w3rx-r6r6-pgpr'],
      },
      {
        name: 'image-size',
        advisoryUrls: ['https://github.com/advisories/GHSA-w3rx-r6r6-pgpr'],
      },
    ]);

    expect(findUnexpectedVulnerabilities({
      vulnerabilities: {
        unexpected: {
          severity: 'critical',
          via: [{ url: 'https://example.com/advisory' }],
        },
      },
    })).toEqual([
      {
        name: 'unexpected',
        advisoryUrls: ['https://example.com/advisory'],
      },
    ]);
  });
});
