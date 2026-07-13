"use client";

import { DragEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";
import type React from "react";
import Link from "next/link";
import {
  ArrowLeft,
  BedDouble,
  Download,
  Edit3,
  EllipsisVertical,
  GripVertical,
  Hotel,
  Plus,
  Save,
  Settings2,
  Trash2,
  UserRound,
  UsersRound,
  X,
} from "lucide-react";
import { Badge, Button, Card, CardContent, Input, Skeleton } from "@/components/ui";
import { PageHeader } from "@/components/shared/page-header";
import { ROUTES } from "@/constants/routes";
import { operationsApi, type RoomingHotel, type RoomingPassenger, type RoomingRoom, type RoomingSpecialRequest, type RoomingTag, type RoomType } from "../api/operations.api";
import { useRoomingActions, useRoomingWorkspace } from "../hooks/use-operations";
import { HotelCheckinDashboard } from "./hotel-checkin-dashboard";

const ROOM_TYPE_LABELS: Record<RoomType, string> = { single: "Single", twin: "Twin", triple: "Triple" };
const TAGS: Array<{ value: Exclude<RoomingTag, "mixed" | "vip">; label: string }> = [
  { value: "unspecified", label: "Unspecified" },
  { value: "male", label: "Male" },
  { value: "female", label: "Female" },
  { value: "family", label: "Family" },
  { value: "couple", label: "Couple" },
];
const ROOM_TAGS: Array<{ value: Exclude<RoomingTag, "unspecified">; label: string }> = [
  { value: "mixed", label: "Mixed" },
  { value: "male", label: "Male" },
  { value: "female", label: "Female" },
  { value: "family", label: "Family" },
  { value: "couple", label: "Couple" },
  { value: "vip", label: "VIP" },
];
const REQUESTS: Array<{ value: RoomingSpecialRequest; label: string }> = [
  { value: "smoking", label: "Smoking" },
  { value: "wheelchair", label: "Wheelchair" },
  { value: "vip", label: "VIP" },
  { value: "late_arrival", label: "Late arrival" },
];

export function RoomingWorkspacePage({ groupId }: { groupId: string }) {
  const { data, isLoading, error } = useRoomingWorkspace(groupId);
  const actions = useRoomingActions(groupId);
  const [selectedHotelId, setSelectedHotelId] = useState<string | null>(null);
  const [showHotelDialog, setShowHotelDialog] = useState(false);
  const [showRoomsDialog, setShowRoomsDialog] = useState(false);
  const [showHotelEditDialog, setShowHotelEditDialog] = useState(false);
  const [selectedPassenger, setSelectedPassenger] = useState<RoomingPassenger | null>(null);
  const [selectedRoom, setSelectedRoom] = useState<RoomingRoom | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [hotelTab, setHotelTab] = useState<"allocation" | "checkins">("allocation");

  const activeHotel = data?.hotels.find((hotel) => hotel.id === selectedHotelId) ?? data?.hotels[0] ?? null;
  const activeHotelId = activeHotel?.id ?? null;
  const assignmentByPassenger = useMemo(() => {
    const entries = activeHotel?.rooms.flatMap((room) => room.occupants.map((passenger) => [passenger.passenger_id, room.id] as const)) ?? [];
    return new Map(entries);
  }, [activeHotel]);

  const allocate = async (passenger: RoomingPassenger, roomId: string | null) => {
    if (!activeHotel) return;
    setActionError(null);
    try {
      await actions.allocatePassenger.mutateAsync({
        hotelId: activeHotel.id,
        passengerId: passenger.passenger_id,
        room_id: roomId,
        allocation_tag: passenger.allocation_tag === "mixed" || passenger.allocation_tag === "vip" ? "unspecified" : passenger.allocation_tag,
        special_requests: passenger.special_requests,
        roommate_notes: passenger.roommate_notes,
      });
    } catch {
      setActionError("The passenger could not be moved. Check the room capacity and try again.");
    }
  };

  const exportHotel = async () => {
    if (!activeHotel) return;
    setActionError(null);
    try {
      const blob = await operationsApi.exportRoomingHotel(activeHotel.id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${activeHotel.hotel_name.replace(/[^a-z0-9]+/gi, "_").toLowerCase()}_rooming_list.xlsx`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch {
      setActionError("Hotel workbook could not be generated. Try again.");
    }
  };

  if (isLoading) return <RoomingLoading />;
  if (error || !data) return <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">Rooming workspace could not be loaded.</div>;

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title={data.group_name}
        description={data.destination ? `Rooming allocation · ${data.destination}` : "Hotel rooming allocation"}
        actions={(
          <div className="flex items-center gap-2">
            <Button type="button" variant="secondary" onClick={() => setShowHotelDialog(true)}>
              <Plus className="h-4 w-4" /> Add hotel
            </Button>
            {activeHotel && <Button type="button" variant="secondary" onClick={() => void exportHotel()}><Download className="h-4 w-4" /> Export</Button>}
          </div>
        )}
      />

      <Link href={ROUTES.dashboard.rooming as never} className="inline-flex w-fit items-center gap-2 text-sm font-medium text-slate-600 hover:text-blue-700">
        <ArrowLeft className="h-4 w-4" /> All rooming lists
      </Link>

      {actionError && <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">{actionError}</div>}

      {data.hotels.length === 0 ? (
        <EmptyRoomingState passengerCount={data.total_passengers} onCreate={() => setShowHotelDialog(true)} />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 pb-4">
            {data.hotels.map((hotel) => (
              <button key={hotel.id} type="button" onClick={() => setSelectedHotelId(hotel.id)} className={`rounded-lg border px-4 py-2 text-sm font-medium transition-colors ${hotel.id === activeHotelId ? "border-blue-600 bg-blue-600 text-white" : "border-slate-200 bg-white text-slate-700 hover:border-blue-200 hover:bg-blue-50"}`}>
                {hotel.hotel_name}
              </button>
            ))}
          </div>

          {activeHotel && (
            <>
              <HotelSummary hotel={activeHotel} passengerTotal={data.total_passengers} onAddRooms={() => setShowRoomsDialog(true)} onEdit={() => setShowHotelEditDialog(true)} />
              <div className="flex gap-2 border-b"><button onClick={() => setHotelTab("allocation")} className={`px-3 py-2 text-sm font-medium ${hotelTab === "allocation" ? "border-b-2 border-blue-600 text-blue-700" : "text-slate-500"}`}>Allocation</button><button onClick={() => setHotelTab("checkins")} className={`px-3 py-2 text-sm font-medium ${hotelTab === "checkins" ? "border-b-2 border-blue-600 text-blue-700" : "text-slate-500"}`}>Hotel Check-in</button></div>
              {hotelTab === "checkins" ? <HotelCheckinDashboard hotelId={activeHotel.id} /> : <div className="grid items-start gap-5 xl:grid-cols-[310px_minmax(0,1fr)]">
                <PassengerQueue
                  passengers={activeHotel.unallocated_passengers}
                  onDropPassenger={(passenger) => void allocate(passenger, null)}
                  onOpenPassenger={setSelectedPassenger}
                />
                <RoomBoard
                  rooms={activeHotel.rooms}
                  pending={actions.allocatePassenger.isPending || actions.deleteRoom.isPending || actions.updateRoom.isPending}
                  onDropPassenger={(passenger, roomId) => void allocate(passenger, roomId)}
                  onOpenPassenger={setSelectedPassenger}
                  onDeleteRoom={(room) => {
                    if (window.confirm(`Delete room ${room.room_number}? It must be empty.`)) actions.deleteRoom.mutate(room.id);
                  }}
                  onBulkDeleteRooms={async (rooms) => {
                    if (!window.confirm(`Delete ${rooms.length} selected room${rooms.length === 1 ? "" : "s"}?`)) return;
                    setActionError(null);
                    await Promise.all(rooms.map((room) => actions.deleteRoom.mutateAsync(room.id)));
                  }}
                  onEditRoom={setSelectedRoom}
                  onSaveRoom={(room) => {
                    actions.updateRoom.mutate({
                      roomId: room.id,
                      room_number: room.room_number,
                      room_type: room.room_type,
                      allocation_tag: room.allocation_tag,
                      roommate_notes: room.roommate_notes,
                      is_saved: true,
                    });
                  }}
                  onReorder={(roomIds) => void actions.orderRooms.mutate({ hotelId: activeHotel.id, roomIds })}
                />
              </div>}
            </>
          )}
        </>
      )}

      {showHotelDialog && <CreateHotelDialog isLoading={actions.createHotel.isPending} onClose={() => setShowHotelDialog(false)} onCreate={async (body) => { await actions.createHotel.mutateAsync(body); setShowHotelDialog(false); }} />}
      {showHotelEditDialog && activeHotel && <EditHotelDialog hotel={activeHotel} isLoading={actions.updateHotel.isPending} onClose={() => setShowHotelEditDialog(false)} onSave={async (body) => { await actions.updateHotel.mutateAsync({ hotelId: activeHotel.id, ...body }); setShowHotelEditDialog(false); }} />}
      {showRoomsDialog && activeHotel && <GenerateRoomsDialog hotel={activeHotel} isLoading={actions.generateRooms.isPending} onClose={() => setShowRoomsDialog(false)} onCreate={async (body) => { await actions.generateRooms.mutateAsync({ hotelId: activeHotel.id, ...body }); setShowRoomsDialog(false); }} />}
      {selectedRoom && <EditRoomDialog room={selectedRoom} isLoading={actions.updateRoom.isPending} onClose={() => setSelectedRoom(null)} onSave={async (body) => { await actions.updateRoom.mutateAsync({ roomId: selectedRoom.id, ...body }); setSelectedRoom(null); }} />}
      {selectedPassenger && activeHotel && <PassengerPreferencesDialog passenger={selectedPassenger} roomId={assignmentByPassenger.get(selectedPassenger.passenger_id) ?? null} isLoading={actions.allocatePassenger.isPending} onClose={() => setSelectedPassenger(null)} onSave={async (body) => { await actions.allocatePassenger.mutateAsync({ hotelId: activeHotel.id, passengerId: selectedPassenger.passenger_id, ...body }); setSelectedPassenger(null); }} />}
    </div>
  );
}

function HotelSummary({ hotel, passengerTotal, onAddRooms, onEdit }: { hotel: RoomingHotel; passengerTotal: number; onAddRooms: () => void; onEdit: () => void }) {
  const freeBeds = Math.max(0, hotel.capacity_total - hotel.allocated_passenger_count);
  return (
    <Card>
      <CardContent className="flex flex-wrap items-center justify-between gap-4 p-5">
        <div className="flex items-center gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-lg bg-blue-50 text-blue-600"><Hotel className="h-5 w-5" /></span>
          <div>
            <h2 className="font-semibold text-slate-900">{hotel.hotel_name}</h2>
            <p className="mt-0.5 text-sm text-slate-500">{[hotel.city, hotel.check_in_date && hotel.check_out_date ? `${hotel.check_in_date} to ${hotel.check_out_date}` : null].filter(Boolean).join(" · ") || "Hotel stay details not set"}</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StatPill icon={<BedDouble className="h-4 w-4" />} label="rooms" value={hotel.rooms.length} />
          <StatPill icon={<UsersRound className="h-4 w-4" />} label="allocated" value={`${hotel.allocated_passenger_count}/${passengerTotal}`} />
          <StatPill icon={<UserRound className="h-4 w-4" />} label="beds free" value={freeBeds} />
          <Button type="button" variant="secondary" onClick={onEdit}><Edit3 className="h-4 w-4" /> Edit hotel</Button>
          <Button type="button" onClick={onAddRooms}><Plus className="h-4 w-4" /> Generate rooms</Button>
        </div>
      </CardContent>
    </Card>
  );
}

function PassengerQueue({ passengers, onDropPassenger, onOpenPassenger }: { passengers: RoomingPassenger[]; onDropPassenger: (passenger: RoomingPassenger) => void; onOpenPassenger: (passenger: RoomingPassenger) => void }) {
  const [dragging, setDragging] = useState(false);
  const groupedPassengers = groupRoomingPassengers(passengers);
  const drop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    const raw = event.dataTransfer.getData("application/rooming-passenger");
    if (raw) onDropPassenger(JSON.parse(raw) as RoomingPassenger);
  };
  return (
    <Card className={`transition-colors ${dragging ? "border-blue-400 bg-blue-50/40" : ""}`}>
      <CardContent className="p-0">
        <div className="border-b border-slate-200 px-5 py-4"><h2 className="font-semibold text-slate-900">Unallocated passengers</h2><p className="mt-1 text-sm text-slate-500">Drag a passenger into any room.</p></div>
        <div className="min-h-48 space-y-2 p-3" onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={drop}>
          {passengers.length === 0 ? (
            <div className="rounded-lg border border-dashed border-slate-200 px-3 py-8 text-center text-sm text-slate-500">All passengers have a room.</div>
          ) : groupedPassengers.map((group) => (
            group.familyGroupId ? (
              <div key={group.key} className="rounded-xl border border-blue-100 bg-blue-50/45 p-2">
                <div className="mb-2 flex items-center justify-between gap-2 px-1">
                  <span className="text-xs font-bold text-blue-800">{group.label}</span>
                  <span className="rounded-full bg-white px-2 py-0.5 text-[10px] font-semibold text-blue-700">{group.passengers.length} pax</span>
                </div>
                <div className="space-y-2">
                  {group.passengers.map((passenger) => <PassengerCard key={passenger.passenger_id} passenger={passenger} onOpen={() => onOpenPassenger(passenger)} />)}
                </div>
              </div>
            ) : group.passengers.map((passenger) => <PassengerCard key={passenger.passenger_id} passenger={passenger} onOpen={() => onOpenPassenger(passenger)} />)
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function groupRoomingPassengers(passengers: RoomingPassenger[]) {
  const groups = new Map<string, { key: string; familyGroupId: string | null; label: string; passengers: RoomingPassenger[] }>();
  for (const passenger of passengers) {
    const key = passenger.family_group_id ? `family:${passenger.family_group_id}` : `single:${passenger.passenger_id}`;
    const existing = groups.get(key);
    if (existing) {
      existing.passengers.push(passenger);
    } else {
      groups.set(key, {
        key,
        familyGroupId: passenger.family_group_id,
        label: passenger.family_group_label ?? passenger.client_name,
        passengers: [passenger],
      });
    }
  }
  return Array.from(groups.values()).map((group) => ({
    ...group,
    passengers: group.passengers.sort((a, b) => (a.family_member_index ?? 999) - (b.family_member_index ?? 999) || a.client_name.localeCompare(b.client_name)),
  }));
}

function RoomBoard({ rooms, pending, onDropPassenger, onOpenPassenger, onDeleteRoom, onBulkDeleteRooms, onEditRoom, onSaveRoom, onReorder }: { rooms: RoomingRoom[]; pending: boolean; onDropPassenger: (passenger: RoomingPassenger, roomId: string) => void; onOpenPassenger: (passenger: RoomingPassenger) => void; onDeleteRoom: (room: RoomingRoom) => void; onBulkDeleteRooms: (rooms: RoomingRoom[]) => Promise<void>; onEditRoom: (room: RoomingRoom) => void; onSaveRoom: (room: RoomingRoom) => void; onReorder: (roomIds: string[]) => void }) {
  const [selectedRoomIds, setSelectedRoomIds] = useState<string[]>([]);
  if (rooms.length === 0) return <Card><CardContent className="p-12 text-center"><BedDouble className="mx-auto h-9 w-9 text-slate-300" /><h2 className="mt-3 font-semibold text-slate-900">No rooms generated</h2><p className="mt-1 text-sm text-slate-500">Generate single, twin, or triple rooms to start allocation.</p></CardContent></Card>;
  const unsavedRooms = rooms.filter((room) => !room.is_saved);
  const savedRooms = rooms.filter((room) => room.is_saved);
  const selectedRooms = rooms.filter((room) => selectedRoomIds.includes(room.id));
  const toggleRoomSelection = (room: RoomingRoom) => setSelectedRoomIds((current) => current.includes(room.id) ? current.filter((roomId) => roomId !== room.id) : [...current, room.id]);
  const selectAllRooms = () => setSelectedRoomIds(rooms.map((room) => room.id));
  const clearSelection = () => setSelectedRoomIds([]);
  const bulkDelete = async () => {
    await onBulkDeleteRooms(selectedRooms);
    clearSelection();
  };
  return <div className="space-y-7">{selectedRooms.length > 0 && <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm shadow-sm"><span className="font-medium text-slate-700">{selectedRooms.length} room{selectedRooms.length === 1 ? "" : "s"} selected</span><div className="flex items-center gap-2"><Button type="button" size="sm" variant="secondary" onClick={selectAllRooms} disabled={pending || selectedRoomIds.length === rooms.length}>Select all</Button><Button type="button" size="sm" variant="secondary" onClick={clearSelection} disabled={pending}>Clear</Button><Button type="button" size="sm" variant="danger" onClick={() => void bulkDelete()} disabled={pending}>Delete selected</Button></div></div>}<RoomSection title="Rooms to save" description="Unsaved rooms stay at the top. Drag a room card to change its order." rooms={unsavedRooms} allRooms={rooms} pending={pending} selectionMode={selectedRoomIds.length > 0} selectedRoomIds={selectedRoomIds} onToggleRoomSelection={toggleRoomSelection} onDropPassenger={onDropPassenger} onOpenPassenger={onOpenPassenger} onDeleteRoom={onDeleteRoom} onEditRoom={onEditRoom} onSaveRoom={onSaveRoom} onReorder={onReorder} /><RoomSection title="Saved rooms" description="Saved room cards are kept below the active allocation work." rooms={savedRooms} allRooms={rooms} pending={pending} selectionMode={selectedRoomIds.length > 0} selectedRoomIds={selectedRoomIds} onToggleRoomSelection={toggleRoomSelection} onDropPassenger={onDropPassenger} onOpenPassenger={onOpenPassenger} onDeleteRoom={onDeleteRoom} onEditRoom={onEditRoom} onSaveRoom={onSaveRoom} onReorder={onReorder} /></div>;
}

function RoomSection({ title, description, rooms, allRooms, pending, selectionMode, selectedRoomIds, onToggleRoomSelection, onDropPassenger, onOpenPassenger, onDeleteRoom, onEditRoom, onSaveRoom, onReorder }: { title: string; description: string; rooms: RoomingRoom[]; allRooms: RoomingRoom[]; pending: boolean; selectionMode: boolean; selectedRoomIds: string[]; onToggleRoomSelection: (room: RoomingRoom) => void; onDropPassenger: (passenger: RoomingPassenger, roomId: string) => void; onOpenPassenger: (passenger: RoomingPassenger) => void; onDeleteRoom: (room: RoomingRoom) => void; onEditRoom: (room: RoomingRoom) => void; onSaveRoom: (room: RoomingRoom) => void; onReorder: (roomIds: string[]) => void }) {
  const [draggedRoomId, setDraggedRoomId] = useState<string | null>(null);
  const moveRoom = (targetRoomId: string) => {
    if (!draggedRoomId || draggedRoomId === targetRoomId) return;
    const source = allRooms.find((room) => room.id === draggedRoomId);
    const target = allRooms.find((room) => room.id === targetRoomId);
    if (!source || !target || source.is_saved !== target.is_saved) return;
    const sectionRooms = allRooms.filter((room) => room.is_saved === source.is_saved);
    const moved = sectionRooms.filter((room) => room.id !== source.id);
    moved.splice(moved.findIndex((room) => room.id === target.id), 0, source);
    const otherRooms = allRooms.filter((room) => room.is_saved !== source.is_saved);
    onReorder([...(!source.is_saved ? moved : otherRooms), ...(source.is_saved ? moved : otherRooms)].map((room) => room.id));
  };
  return <section><div className="mb-3"><h2 className="font-semibold text-slate-900">{title} <span className="text-sm font-medium text-slate-400">({rooms.length})</span></h2><p className="mt-1 text-sm text-slate-500">{description}</p></div>{rooms.length === 0 ? <div className="rounded-lg border border-dashed border-slate-200 bg-white px-4 py-6 text-sm text-slate-500">No rooms in this section.</div> : <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">{rooms.map((room) => <RoomCard key={room.id} room={room} pending={pending} selectionMode={selectionMode} selected={selectedRoomIds.includes(room.id)} onToggleSelected={() => onToggleRoomSelection(room)} onDropPassenger={onDropPassenger} onOpenPassenger={onOpenPassenger} onDelete={() => onDeleteRoom(room)} onEdit={() => onEditRoom(room)} onSave={() => onSaveRoom(room)} onDragStart={() => setDraggedRoomId(room.id)} onDragEnd={() => setDraggedRoomId(null)} onDropRoom={() => moveRoom(room.id)} />)}</div>}</section>;
}

function RoomCard({ room, pending, selectionMode, selected, onToggleSelected, onDropPassenger, onOpenPassenger, onDelete, onEdit, onSave, onDragStart, onDragEnd, onDropRoom }: { room: RoomingRoom; pending: boolean; selectionMode: boolean; selected: boolean; onToggleSelected: () => void; onDropPassenger: (passenger: RoomingPassenger, roomId: string) => void; onOpenPassenger: (passenger: RoomingPassenger) => void; onDelete: () => void; onEdit: () => void; onSave: () => void; onDragStart: () => void; onDragEnd: () => void; onDropRoom: () => void }) {
  const [dragging, setDragging] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const isFull = room.occupants.length >= room.capacity;

  useEffect(() => {
    if (!menuOpen) return;

    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };

    document.addEventListener("pointerdown", closeOnOutsidePointer);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [menuOpen]);

  const drop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    const raw = event.dataTransfer.getData("application/rooming-passenger");
    if (raw && !isFull) onDropPassenger(JSON.parse(raw) as RoomingPassenger, room.id);
  };
  const toggleFromCard = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!selectionMode) return;
    if ((event.target as HTMLElement).closest("button,input,select,textarea,a,[draggable='true']")) return;
    onToggleSelected();
  };
  return (
    <Card onClick={toggleFromCard} onDragOver={(event) => { if (event.dataTransfer.types.includes("application/rooming-room")) event.preventDefault(); }} onDrop={(event) => { if (event.dataTransfer.getData("application/rooming-room")) { event.preventDefault(); onDropRoom(); return; } drop(event); }} className={`overflow-visible transition-colors ${selectionMode ? "cursor-pointer" : ""} ${selected ? "border-blue-400 ring-2 ring-blue-100" : dragging && !isFull ? "border-blue-400 bg-blue-50/40" : ""}`}>
      <CardContent className="p-0">
        <div className="flex items-start justify-between gap-3 border-b border-slate-100 px-4 py-3.5">
          <div>
            <div className="flex items-center gap-2">
              <input type="checkbox" checked={selected} onChange={onToggleSelected} className="h-4 w-4 rounded border-slate-300 text-blue-600" aria-label={`Select room ${room.room_number}`} />
              <span draggable onDragStart={(event) => { event.dataTransfer.effectAllowed = "move"; event.dataTransfer.setData("application/rooming-room", room.id); onDragStart(); }} onDragEnd={onDragEnd} className="cursor-grab text-slate-300 active:cursor-grabbing" title="Drag to reorder this room"><GripVertical className="h-4 w-4" /></span>
              <span className="font-semibold text-slate-900">{room.room_number}</span>
              <Badge variant="secondary">{ROOM_TYPE_LABELS[room.room_type]}</Badge>
            </div>
            <p className="mt-1 text-xs text-slate-500">{room.allocation_tag === "mixed" ? "Mixed allocation" : `${room.allocation_tag} allocation`} · {room.occupants.length}/{room.capacity}</p>
          </div>
          <div ref={menuRef} className="relative"><button type="button" onClick={() => setMenuOpen((open) => !open)} className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700" aria-label={`Room ${room.room_number} actions`} aria-expanded={menuOpen} aria-haspopup="menu"><EllipsisVertical className="h-4 w-4" /></button>{menuOpen && <div role="menu" className="absolute right-0 top-7 z-20 w-36 rounded-lg border border-slate-200 bg-white py-1 shadow-lg">{!room.is_saved && <button type="button" role="menuitem" onClick={() => { setMenuOpen(false); onSave(); }} disabled={pending} className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium text-emerald-700 hover:bg-emerald-50 disabled:cursor-not-allowed disabled:opacity-40"><Save className="h-3.5 w-3.5" /> Save room</button>}<button type="button" role="menuitem" onClick={() => { setMenuOpen(false); onEdit(); }} className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium text-slate-700 hover:bg-slate-50"><Edit3 className="h-3.5 w-3.5" /> Edit</button><button type="button" role="menuitem" onClick={() => { setMenuOpen(false); onDelete(); }} disabled={pending} className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium text-red-600 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-40"><Trash2 className="h-3.5 w-3.5" /> Delete</button></div>}</div>
        </div>
        <div className="min-h-40 space-y-2 p-3" onDragOver={(event) => { event.preventDefault(); if (!isFull) setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={drop}>
          {room.occupants.map((passenger) => <PassengerCard key={passenger.passenger_id} passenger={passenger} onOpen={() => onOpenPassenger(passenger)} />)}
          {!isFull && <div className="rounded-md border border-dashed border-slate-200 px-3 py-2 text-center text-xs text-slate-400">Drop passenger here</div>}
        </div>
        {room.roommate_notes && <div className="border-t border-slate-100 px-4 py-3 text-xs text-slate-500"><span className="font-medium text-slate-700">Room notes:</span> {room.roommate_notes}</div>}
      </CardContent>
    </Card>
  );
}
function PassengerCard({ passenger, onOpen }: { passenger: RoomingPassenger; onOpen: () => void }) {
  return (
    <div draggable onDragStart={(event) => { event.dataTransfer.effectAllowed = "move"; event.dataTransfer.setData("application/rooming-passenger", JSON.stringify(passenger)); }} className="group flex cursor-grab items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2.5 shadow-sm active:cursor-grabbing">
      <GripVertical className="h-4 w-4 shrink-0 text-slate-300" />
      <div className="min-w-0 flex-1"><div className="break-words text-sm font-medium text-slate-900">{passenger.client_name}</div><div className="mt-0.5 flex flex-wrap gap-1">{passenger.family_relation && <TagBadge label={passenger.family_relation} />}{passenger.allocation_tag !== "unspecified" && <TagBadge label={passenger.allocation_tag} />}{passenger.family_group_label && <FamilyBadge label={passenger.family_size === 2 ? "couple" : "family"} />}{passenger.special_requests.map((request) => <RequestBadge key={request} request={request} />)}</div></div>
      <button type="button" onClick={onOpen} className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700" aria-label={`Edit ${passenger.client_name} rooming preferences`}><Settings2 className="h-4 w-4" /></button>
    </div>
  );
}

function CreateHotelDialog({ isLoading, onClose, onCreate }: { isLoading: boolean; onClose: () => void; onCreate: (body: { hotel_name: string; city?: string; check_in_date?: string; check_out_date?: string }) => Promise<void> }) {
  const [form, setForm] = useState({ hotel_name: "", city: "", check_in_date: "", check_out_date: "" });
  const [error, setError] = useState<string | null>(null);
  const submit = async (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); setError(null); try { await onCreate({ hotel_name: form.hotel_name, city: form.city || undefined, check_in_date: form.check_in_date || undefined, check_out_date: form.check_out_date || undefined }); } catch { setError("Hotel could not be created. Check the stay dates and try again."); } };
  return <DialogShell title="Add hotel stay" icon={<Hotel className="h-5 w-5" />} onClose={onClose}><form className="space-y-4" onSubmit={submit}><Input label="Hotel name" placeholder="Marriott Bangkok" value={form.hotel_name} onChange={(event) => setForm((current) => ({ ...current, hotel_name: event.target.value }))} required /><Input label="City" placeholder="Bangkok" value={form.city} onChange={(event) => setForm((current) => ({ ...current, city: event.target.value }))} /><div className="grid grid-cols-2 gap-3"><Input label="Check-in" type="date" value={form.check_in_date} onChange={(event) => setForm((current) => ({ ...current, check_in_date: event.target.value }))} /><Input label="Check-out" type="date" value={form.check_out_date} onChange={(event) => setForm((current) => ({ ...current, check_out_date: event.target.value }))} /></div>{error && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}<DialogActions onClose={onClose} isLoading={isLoading} label="Add hotel" /></form></DialogShell>;
}

function EditHotelDialog({ hotel, isLoading, onClose, onSave }: { hotel: RoomingHotel; isLoading: boolean; onClose: () => void; onSave: (body: { hotel_name: string; city?: string; check_in_date?: string; check_out_date?: string; room_count?: number }) => Promise<void> }) {
  const [form, setForm] = useState({ hotel_name: hotel.hotel_name, city: hotel.city ?? "", check_in_date: hotel.check_in_date ?? "", check_out_date: hotel.check_out_date ?? "", room_count: String(hotel.rooms.length) });
  const [error, setError] = useState<string | null>(null);
  const submit = async (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); setError(null); try { await onSave({ hotel_name: form.hotel_name, city: form.city || undefined, check_in_date: form.check_in_date || undefined, check_out_date: form.check_out_date || undefined, room_count: Number(form.room_count) }); } catch { setError("Hotel details could not be saved. Occupied rooms cannot be removed."); } };
  return <DialogShell title="Edit hotel stay" icon={<Hotel className="h-5 w-5" />} onClose={onClose}><form className="space-y-4" onSubmit={submit}><Input label="Hotel name" value={form.hotel_name} onChange={(event) => setForm((current) => ({ ...current, hotel_name: event.target.value }))} required /><Input label="City" value={form.city} onChange={(event) => setForm((current) => ({ ...current, city: event.target.value }))} /><div className="grid grid-cols-2 gap-3"><Input label="Check-in" type="date" value={form.check_in_date} onChange={(event) => setForm((current) => ({ ...current, check_in_date: event.target.value }))} /><Input label="Check-out" type="date" value={form.check_out_date} onChange={(event) => setForm((current) => ({ ...current, check_out_date: event.target.value }))} /></div><Input label="Total rooms" type="number" min="0" max="500" value={form.room_count} onChange={(event) => setForm((current) => ({ ...current, room_count: event.target.value }))} required /><p className="text-xs text-slate-500">Adding rooms copies the last room type. Reducing rooms only removes empty rooms from the end.</p>{error && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}<DialogActions onClose={onClose} isLoading={isLoading} label="Save hotel" /></form></DialogShell>;
}

function EditRoomDialog({ room, isLoading, onClose, onSave }: { room: RoomingRoom; isLoading: boolean; onClose: () => void; onSave: (body: { room_number: string; room_type: RoomType; allocation_tag: Exclude<RoomingTag, "unspecified">; roommate_notes?: string | null; is_saved: boolean }) => Promise<void> }) {
  const [form, setForm] = useState({ room_number: room.room_number, room_type: room.room_type, allocation_tag: room.allocation_tag, roommate_notes: room.roommate_notes ?? "", is_saved: room.is_saved });
  const [error, setError] = useState<string | null>(null);
  const submit = async (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); setError(null); try { await onSave({ ...form, roommate_notes: form.roommate_notes || null }); } catch { setError("Room could not be saved. Use a unique room number and keep enough beds for its occupants."); } };
  return <DialogShell title={`Edit room ${room.room_number}`} icon={<BedDouble className="h-5 w-5" />} onClose={onClose}><form className="space-y-4" onSubmit={submit}><Input label="Room number" value={form.room_number} onChange={(event) => setForm((current) => ({ ...current, room_number: event.target.value }))} required /><div className="grid grid-cols-2 gap-3"><label className="block text-sm font-medium text-slate-700">Room type<select className="mt-1.5 h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" value={form.room_type} onChange={(event) => setForm((current) => ({ ...current, room_type: event.target.value as RoomType }))}>{(["single", "twin", "triple"] as RoomType[]).map((type) => <option key={type} value={type}>{ROOM_TYPE_LABELS[type]}</option>)}</select></label><label className="block text-sm font-medium text-slate-700">Allocation type<select className="mt-1.5 h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" value={form.allocation_tag} onChange={(event) => setForm((current) => ({ ...current, allocation_tag: event.target.value as Exclude<RoomingTag, "unspecified"> }))}>{ROOM_TAGS.map((tag) => <option key={tag.value} value={tag.value}>{tag.label}</option>)}</select></label></div><label className="block text-sm font-medium text-slate-700">Room notes<textarea className="mt-1.5 min-h-20 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" value={form.roommate_notes} onChange={(event) => setForm((current) => ({ ...current, roommate_notes: event.target.value }))} /></label><label className="flex items-center gap-2 text-sm font-medium text-slate-700"><input type="checkbox" checked={form.is_saved} onChange={(event) => setForm((current) => ({ ...current, is_saved: event.target.checked }))} /> Mark this room as saved</label>{error && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}<DialogActions onClose={onClose} isLoading={isLoading} label="Save room" /></form></DialogShell>;
}
function GenerateRoomsDialog({ hotel, isLoading, onClose, onCreate }: { hotel: RoomingHotel; isLoading: boolean; onClose: () => void; onCreate: (body: { room_type: RoomType; count: number; starting_number?: number; allocation_tag: Exclude<RoomingTag, "unspecified"> }) => Promise<void> }) {
  const [form, setForm] = useState<{ room_type: RoomType; count: string; starting_number: string; allocation_tag: Exclude<RoomingTag, "unspecified"> }>({ room_type: "twin", count: "10", starting_number: "", allocation_tag: "mixed" });
  const [error, setError] = useState<string | null>(null);
  const submit = async (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); setError(null); try { await onCreate({ room_type: form.room_type, count: Number(form.count), starting_number: form.starting_number ? Number(form.starting_number) : undefined, allocation_tag: form.allocation_tag }); } catch { setError("Rooms could not be generated. Room numbers may already exist."); } };
  return <DialogShell title={`Generate rooms · ${hotel.hotel_name}`} icon={<BedDouble className="h-5 w-5" />} onClose={onClose}><form className="space-y-4" onSubmit={submit}><div className="grid grid-cols-3 gap-2">{(["single", "twin", "triple"] as RoomType[]).map((type) => <button key={type} type="button" onClick={() => setForm((current) => ({ ...current, room_type: type }))} className={`rounded-lg border px-3 py-2 text-sm font-medium ${form.room_type === type ? "border-blue-600 bg-blue-50 text-blue-700" : "border-slate-200 text-slate-600 hover:bg-slate-50"}`}>{ROOM_TYPE_LABELS[type]}</button>)}</div><div className="grid grid-cols-2 gap-3"><Input label="Number of rooms" type="number" min="1" max="500" value={form.count} onChange={(event) => setForm((current) => ({ ...current, count: event.target.value }))} required /><Input label="Start room number" type="number" placeholder="Auto" value={form.starting_number} onChange={(event) => setForm((current) => ({ ...current, starting_number: event.target.value }))} /></div><label className="block text-sm font-medium text-slate-700">Allocation type<select className="mt-1.5 h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" value={form.allocation_tag} onChange={(event) => setForm((current) => ({ ...current, allocation_tag: event.target.value as Exclude<RoomingTag, "unspecified"> }))}>{ROOM_TAGS.map((tag) => <option key={tag.value} value={tag.value}>{tag.label}</option>)}</select></label>{error && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}<DialogActions onClose={onClose} isLoading={isLoading} label="Generate rooms" /></form></DialogShell>;
}

function PassengerPreferencesDialog({ passenger, roomId, isLoading, onClose, onSave }: { passenger: RoomingPassenger; roomId: string | null; isLoading: boolean; onClose: () => void; onSave: (body: { room_id: string | null; allocation_tag: Exclude<RoomingTag, "mixed" | "vip">; special_requests: RoomingSpecialRequest[]; roommate_notes?: string | null }) => Promise<void> }) {
  const [tag, setTag] = useState<Exclude<RoomingTag, "mixed" | "vip">>(passenger.allocation_tag === "mixed" || passenger.allocation_tag === "vip" ? "unspecified" : passenger.allocation_tag);
  const [requests, setRequests] = useState<RoomingSpecialRequest[]>(passenger.special_requests);
  const [notes, setNotes] = useState(passenger.roommate_notes ?? "");
  const [error, setError] = useState<string | null>(null);
  const submit = async (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); setError(null); try { await onSave({ room_id: roomId, allocation_tag: tag, special_requests: requests, roommate_notes: notes || null }); } catch { setError("Passenger preferences could not be saved."); } };
  return <DialogShell title={passenger.client_name} icon={<UserRound className="h-5 w-5" />} onClose={onClose}><form className="space-y-5" onSubmit={submit}><label className="block text-sm font-medium text-slate-700">Rooming tag<select className="mt-1.5 h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" value={tag} onChange={(event) => setTag(event.target.value as Exclude<RoomingTag, "mixed" | "vip">)}>{TAGS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label><div><p className="text-sm font-medium text-slate-700">Special requests</p><div className="mt-2 flex flex-wrap gap-2">{REQUESTS.map((request) => { const selected = requests.includes(request.value); return <button key={request.value} type="button" onClick={() => setRequests((current) => selected ? current.filter((value) => value !== request.value) : [...current, request.value])} className={`rounded-full border px-3 py-1.5 text-xs font-medium ${selected ? "border-blue-600 bg-blue-50 text-blue-700" : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"}`}>{request.label}</button>; })}</div></div><label className="block text-sm font-medium text-slate-700">Roommate notes<textarea className="mt-1.5 min-h-24 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" placeholder="Keep with family, quiet room, medical note for hotel..." value={notes} onChange={(event) => setNotes(event.target.value)} /></label>{error && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}<DialogActions onClose={onClose} isLoading={isLoading} label="Save preferences" /></form></DialogShell>;
}

function DialogShell({ title, icon, onClose, children }: { title: string; icon: React.ReactNode; onClose: () => void; children: React.ReactNode }) { return <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4 backdrop-blur-sm"><Card className="w-full max-w-lg overflow-hidden shadow-2xl"><CardContent className="p-6"><div className="mb-5 flex items-start justify-between gap-4"><div className="flex items-center gap-3"><span className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-600">{icon}</span><h2 className="font-semibold text-slate-900">{title}</h2></div><button type="button" onClick={onClose} className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"><X className="h-5 w-5" /><span className="sr-only">Close</span></button></div>{children}</CardContent></Card></div>; }
function DialogActions({ onClose, isLoading, label }: { onClose: () => void; isLoading: boolean; label: string }) { return <div className="flex justify-end gap-3 pt-1"><Button type="button" variant="secondary" onClick={onClose} disabled={isLoading}>Cancel</Button><Button type="submit" isLoading={isLoading}>{label}</Button></div>; }
function StatPill({ icon, label, value }: { icon: React.ReactNode; label: string; value: string | number }) { return <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600"><span className="text-slate-400">{icon}</span><span className="text-slate-900">{value}</span><span>{label}</span></span>; }
function TagBadge({ label }: { label: string }) { return <span className="rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium capitalize text-slate-600">{label}</span>; }
function FamilyBadge({ label }: { label: string }) { return <span className="rounded-full bg-blue-50 px-1.5 py-0.5 text-[10px] font-semibold capitalize text-blue-700">{label}</span>; }
function RequestBadge({ request }: { request: RoomingSpecialRequest }) { const label = REQUESTS.find((item) => item.value === request)?.label ?? request; return <span className="rounded-full bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">{label}</span>; }
function EmptyRoomingState({ passengerCount, onCreate }: { passengerCount: number; onCreate: () => void }) { return <Card><CardContent className="p-12 text-center"><Hotel className="mx-auto h-10 w-10 text-blue-500" /><h2 className="mt-4 text-lg font-semibold text-slate-900">Add the first hotel stay</h2><p className="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-500">{passengerCount} confirmed passengers are ready for allocation. Add a hotel, generate rooms, then drag each passenger into a room.</p><Button type="button" className="mt-5" onClick={onCreate}><Plus className="h-4 w-4" /> Add hotel</Button></CardContent></Card>; }
function RoomingLoading() { return <div className="space-y-5"><Skeleton className="h-16" /><Skeleton className="h-24" /><div className="grid gap-5 xl:grid-cols-[310px_minmax(0,1fr)]"><Skeleton className="h-96" /><Skeleton className="h-96" /></div></div>; }
