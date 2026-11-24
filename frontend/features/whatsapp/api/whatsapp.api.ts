import { uploadWelcomeImage } from './broadcast-media.api';
import { whatsappGroupsApi } from './broadcast-groups.api';
import { whatsappRecipientsApi } from './broadcast-recipients.api';
import { whatsappMessageReadsApi } from './broadcast-message-reads.api';

export type * from '../types/recipients';
export type * from '../types/groups';
export type * from '../types/messages';

/** Compatibility entry point; each transport owner keeps its original method contract. */
export const whatsappApi = {
  ...whatsappGroupsApi,
  ...whatsappRecipientsApi,
  ...whatsappMessageReadsApi,
  uploadWelcomeImage,
};
