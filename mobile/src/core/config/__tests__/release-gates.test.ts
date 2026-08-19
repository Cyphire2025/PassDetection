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

  it('allows only the explicit Metro build-time audit root causes', () => {
    const allowedReport = {
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
    expect(findUnexpectedVulnerabilities(allowedReport)).toEqual([]);

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
