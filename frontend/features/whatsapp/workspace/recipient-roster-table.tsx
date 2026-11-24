import { Eye, Pencil, Trash2 } from "lucide-react";
import type { Dispatch, SetStateAction } from "react";
import type { WhatsAppBroadcastGroupDetail } from "../api/whatsapp.api";
import { RecipientPhoneCell, RecipientRowMenu } from "./recipient-controls";
import { DeliveryBadge, tableClass, WorkspacePagination } from "./workspace-ui";
import { welcomeStatus, type RecipientPerson } from "./recipient-roster-model";
import type { RecipientRoster } from "./use-recipient-roster";

export function RecipientRosterTable({ roster, group, editingPhone, setEditingPhone, setRemoving }: {
  roster: RecipientRoster;
  group: WhatsAppBroadcastGroupDetail;
  editingPhone: string | null;
  setEditingPhone: Dispatch<SetStateAction<string | null>>;
  setRemoving: Dispatch<SetStateAction<RecipientPerson | null>>;
}) {
  const { displayed, pageOffset, openDetails, setOpenDetails, setOffset } = roster;
  return (
    <>
      <div className="overflow-x-auto">
        <table className={tableClass}>
          <thead>
            <tr>
              <th>Recipient</th>
              <th>WhatsApp number</th>
              <th>Welcome status</th>
              <th>
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {displayed
              .slice(pageOffset, pageOffset + 50)
              .map((person) => (
                <tr
                  key={person.key}
                  className={
                    openDetails.includes(person.key)
                      ? "bg-blue-50/40"
                      : ""
                  }
                >
                  <td>
                    <p className="font-medium text-slate-900">
                      {person.name}
                    </p>
                    {person.mergedId && (
                      <p className="mt-1 text-xs text-slate-400">
                        Shared WhatsApp number
                      </p>
                    )}
                  </td>
                  <td>
                    <RecipientPhoneCell
                      groupId={group.id}
                      recipientId={person.recipient.id}
                      number={person.recipient.normalized_phone_number}
                      editing={editingPhone === person.key}
                      disabled={group.is_archived}
                      onEdit={() => setEditingPhone(person.key)}
                      onDone={() => setEditingPhone(null)}
                    />
                  </td>
                  <td>
                    <DeliveryBadge status={welcomeStatus(person)} />
                  </td>
                  <td className="text-right">
                    <RecipientRowMenu name={person.name}>
                      {(close) => (
                        <>
                          <button
                            role="menuitem"
                            onClick={() => {
                              setOpenDetails((current) =>
                                current.includes(person.key)
                                  ? current
                                  : [...current, person.key],
                              );
                              close();
                            }}
                          >
                            <Eye className="h-3.5 w-3.5" />
                            View details
                          </button>
                          {!group.is_archived && (
                            <>
                              <button
                                role="menuitem"
                                onClick={() => {
                                  setEditingPhone(person.key);
                                  close();
                                }}
                              >
                                <Pencil className="h-3.5 w-3.5" />
                                Edit WhatsApp number
                              </button>
                              <div className="my-1 border-t border-slate-100" />
                              <button
                                role="menuitem"
                                className="text-red-600 disabled:opacity-40"
                                disabled={group.recipients.length <= 1}
                                onClick={() => {
                                  setRemoving(person);
                                  close();
                                }}
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                                Remove recipient
                              </button>
                            </>
                          )}
                        </>
                      )}
                    </RecipientRowMenu>
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
      <WorkspacePagination
        total={displayed.length}
        offset={pageOffset}
        limit={50}
        onChange={setOffset}
        label="Recipients"
      />
    </>

  );
}
