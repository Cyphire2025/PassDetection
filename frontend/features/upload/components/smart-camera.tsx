"use client";

import { usePassportCamera } from "../hooks/use-passport-camera";
import { PassportCameraView } from "./passport-camera-view";
import type { SmartCameraProps } from "./passport-camera.types";

export function SmartCamera(props: SmartCameraProps) {
  return <PassportCameraView camera={usePassportCamera(props)} />;
}
