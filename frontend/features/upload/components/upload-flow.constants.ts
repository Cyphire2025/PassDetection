export const MIN_FAMILY_MEMBERS = 2;

export const MAX_FAMILY_MEMBERS = 20;

export const REVIEW_FIELDS = [
  "surname",
  "given_names",
  "passport_number",
  "nationality",
  "place_of_issue",
  "date_of_birth",
  "date_of_issue",
  "date_of_expiry",
  "sex",
] as const;

export const REQUIRED_REVIEW_FIELDS = REVIEW_FIELDS.filter(
  (field) => field !== "date_of_issue" && field !== "surname",
);

export const FAMILY_RELATIONS = [
  "Head",
  "Spouse",
  "Son",
  "Daughter",
  "Father",
  "Mother",
  "Brother",
  "Sister",
  "Other",
];

export const GENDERS = ["Male", "Female", "Other", "Prefer not to say"];
