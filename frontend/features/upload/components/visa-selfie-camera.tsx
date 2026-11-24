"use client";

import { type VisaSelfieCameraProps } from "./visa-camera.types";
import { useVisaCamera } from "../hooks/use-visa-camera";
import { VisaCameraView } from "./visa-camera-view";

export function VisaSelfieCamera(props: VisaSelfieCameraProps) {
  const camera = useVisaCamera(props);
  return <VisaCameraView camera={camera} />;
}
