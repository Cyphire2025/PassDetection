"use client";

import Image from "next/image";
import { FileText, ImageIcon, Loader2, MessageSquare, Plus, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { assistantApi, assistantMessage } from "../api";
import { useDialogFocus } from "../hooks/use-dialog-focus";
import type { Asset, Conversation } from "../types";
import styles from "./panels.module.css";

export function WorkspaceDrawer({ kind, signedIn, onClose, onImage, onConversation, onNew, onDelete }: {
  kind: "library" | "history" | null; signedIn: boolean; onClose: () => void;
  onImage: (asset: Asset, images: Asset[]) => void; onConversation: (id: string) => void; onNew: () => void;
  onDelete: (id: string) => Promise<void>;
}) {
  const root = useRef<HTMLDivElement>(null);
  const [files, setFiles] = useState<Asset[]>([]);
  const [chats, setChats] = useState<Conversation[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<"images" | "files">("images");
  const sequence = useRef(0);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const cancelDelete = useRef<HTMLButtonElement>(null);
  const newChat = useRef<HTMLButtonElement>(null);
  useEffect(() => { if (confirmDelete) cancelDelete.current?.focus(); }, [confirmDelete]);
  const remove = async (id: string) => {
    if (deleting) return;
    setDeleting(true); setDeleteError("");
    try {
      await onDelete(id);
      sequence.current++; setLoading(false);
      setChats((current) => current.filter((chat) => chat.id !== id)); setConfirmDelete(null);
      newChat.current?.focus();
    } catch (cause) { setDeleteError(assistantMessage(cause, "This conversation could not be deleted. Please try again.")); }
    finally { setDeleting(false); }
  };
  useDialogFocus(Boolean(kind), root, onClose);
  const load = useCallback(async (next?: string) => {
    if (!kind || !signedIn) return;
    const request = ++sequence.current; setLoading(true); setError("");
    try {
      if (kind === "library") { const page = await assistantApi.assets(next); if (sequence.current !== request) return; setFiles((old) => next ? [...old, ...page.items] : page.items); setCursor(page.next_cursor); }
      else { const page = await assistantApi.conversations(next); if (sequence.current !== request) return; setChats((old) => next ? [...old, ...page.items] : page.items); setCursor(page.next_cursor); }
    } catch { if (sequence.current === request) setError("Your workspace could not be loaded. Please try again."); }
    finally { if (sequence.current === request) setLoading(false); }
  }, [kind, signedIn]);
  useEffect(() => {
    let active = true;
    // Load after mounting; every drawer instance owns one kind and a fresh page state.
    queueMicrotask(() => { if (active && kind) void load(); });
    return () => { active = false; };
  }, [kind, load]);
  if (!kind) return null;
  const images = files.filter((file) => file.mime.startsWith("image/")).sort((a, b) => b.created_at.localeCompare(a.created_at));
  const documents = files.filter((file) => !file.mime.startsWith("image/"));
  return <div className={styles.overlay}>
    <button className={styles.scrim} type="button" onClick={onClose} aria-label="Close workspace panel" tabIndex={-1} />
    <div className={styles.drawer} ref={root} role="dialog" aria-modal="true" aria-labelledby="workspace-drawer-title">
      <div className={styles.drawerHeader}><div><p>GLOBAL CONNECTS</p><h2 id="workspace-drawer-title">{kind === "library" ? "Your library" : "Conversations"}</h2></div><button type="button" className={styles.iconButton} onClick={onClose} aria-label="Close panel"><X size={19} /></button></div>
      {!signedIn ? <div className={styles.empty}><MessageSquare size={25} /><h3>A space of your own</h3><p>Sign in to access your private conversations and images.</p><a href="/session-restore?from=%2Fai" className={styles.primary}>Sign in to Global Connects</a></div> : <>
        {kind === "library" ? <div className={styles.tabs}><button type="button" aria-pressed={filter === "images"} onClick={() => setFilter("images")}><ImageIcon size={14} />Images</button><button type="button" aria-pressed={filter === "files"} onClick={() => setFilter("files")}><FileText size={14} />Files</button></div> : <button ref={newChat} type="button" className={styles.newChat} onClick={() => { onNew(); onClose(); }}><Plus size={16} />New conversation</button>}
        <div className={styles.drawerBody}>
          {loading && !files.length && !chats.length ? <div className={styles.empty} role="status"><Loader2 className={styles.spinner} size={24} /><p>Opening your workspace…</p></div> : null}
          {error ? <div className={styles.empty} role="alert"><p>{error}</p><button type="button" onClick={() => void load()} className={styles.secondary}>Try again</button></div> : null}
          {!loading && !error && ((kind === "history" && !chats.length) || (kind === "library" && !(filter === "images" ? images : documents).length)) ? <div className={styles.empty}>{kind === "library" ? <ImageIcon size={28} /> : <MessageSquare size={28} />}<h3>{kind === "history" ? "A fresh beginning" : "Room for inspiration"}</h3><p>{kind === "history" ? "Your saved conversations will appear here." : "Images you create and files you upload will be kept here, just for you."}</p></div> : null}
          {kind === "library" && filter === "images" ? <div className={styles.libraryGrid}>{images.map((image) => <button type="button" key={image.id} onClick={() => { onImage(image, images); onClose(); }} aria-label={`View ${image.name}`}><div><Image src={image.url} alt={image.name} fill unoptimized sizes="190px" /></div><span>{image.name}</span><small>{image.kind === "generated" ? "Created with AI" : "Uploaded image"}</small></button>)}</div> : null}
          {kind === "library" && filter === "files" ? documents.map((file) => <a className={styles.fileRow} href={file.url} key={file.id} download><FileText size={21} /><span>{file.name}<small>{(file.size / 1024).toFixed(0)} KB</small></span></a>) : null}
          {kind === "history" ? [...chats].sort((a, b) => b.created_at.localeCompare(a.created_at)).map((chat) => <div key={chat.id} className={styles.historyItem}>
            <div className={styles.historyRow}><button type="button" className={styles.chatRow} disabled={deleting} onClick={() => { onConversation(chat.id); onClose(); }}><MessageSquare size={16} /><span>{chat.title}<small>{new Date(chat.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}</small></span></button><button type="button" className={styles.deleteChat} disabled={deleting} data-delete-conversation={chat.id} aria-label={`Delete ${chat.title}`} aria-expanded={confirmDelete === chat.id} onClick={() => { setConfirmDelete(chat.id); setDeleteError(""); }}><Trash2 size={15} /></button></div>
            {confirmDelete === chat.id ? <div className={styles.deleteConfirmation} role="group" aria-label={`Delete conversation: ${chat.title}`} aria-busy={deleting}>
              <p>Delete this conversation?</p><small>Its messages will be removed. Images and files in your library stay available.</small>
              {deleteError ? <p role="alert" className={styles.deleteError}>{deleteError}</p> : null}
              <div><button ref={cancelDelete} type="button" disabled={deleting} onClick={() => { setConfirmDelete(null); requestAnimationFrame(() => root.current?.querySelector<HTMLButtonElement>(`[data-delete-conversation="${chat.id}"]`)?.focus()); }}>Cancel</button><button type="button" disabled={deleting} onClick={() => void remove(chat.id)}>{deleting ? <Loader2 size={13} className={styles.spinner} /> : <Trash2 size={13} />}{deleting ? "Deleting…" : "Delete conversation"}</button></div>
            </div> : null}
          </div>) : null}
          {cursor ? <button type="button" className={styles.loadMore} disabled={loading} onClick={() => void load(cursor)}>{loading ? "Loading…" : "Load more"}</button> : null}
        </div>
      </>}
      <p className={styles.drawerFooter}>Private to your account. Access follows your MCP connection and AI settings.</p>
    </div>
  </div>;
}
