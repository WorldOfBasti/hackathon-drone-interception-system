import SwiftUI

struct ContentView: View {
    @StateObject private var sessionManager = ARSessionManager()
    @State private var isShowingRecordings = false
    @AppStorage("deviceID") private var deviceID = "iphone1"
    private let portraitCameraAspectRatio: CGFloat = 9.0 / 16.0

    var body: some View {
        GeometryReader { geometry in
            ZStack(alignment: .bottom) {
                cameraStage(in: geometry.size)

                debugDeck
                    .padding(.horizontal, 10)
                    .padding(.bottom, max(geometry.safeAreaInsets.bottom, 10))
            }
            .frame(width: geometry.size.width, height: geometry.size.height)
            .background(Color.black)
            .clipped()
        }
        .ignoresSafeArea()
        .onAppear {
            sessionManager.startSession()
        }
        .onDisappear {
            sessionManager.pauseSession()
        }
        .alert(item: $sessionManager.alert) { alert in
            Alert(
                title: Text(alert.title),
                message: Text(alert.message),
                dismissButton: .default(Text("OK"))
            )
        }
        .sheet(isPresented: $isShowingRecordings) {
            RecordingExportsView(isRecording: sessionManager.isRecording)
        }
    }

    private func cameraStage(in container: CGSize) -> some View {
        let size = fillingPortraitCameraSize(in: container)

        return cameraFeed
            .frame(width: size.width, height: size.height)
            .position(x: container.width / 2, y: container.height / 2)
    }

    private var cameraFeed: some View {
        ZStack {
            ARCameraView(sessionManager: sessionManager)
                .overlay {
                    GeometryReader { geometry in
                        Color.clear
                            .contentShape(Rectangle())
                            .gesture(
                                DragGesture(minimumDistance: 0)
                                    .onEnded { value in
                                        sessionManager.storeTap(
                                            at: value.location,
                                            viewportSize: geometry.size
                                        )
                                    }
                            )
                    }
                }

            DebugReticleOverlay(isRecording: sessionManager.isRecording)
                .allowsHitTesting(false)
        }
        .clipped()
    }

    private func fillingPortraitCameraSize(in container: CGSize) -> CGSize {
        guard container.width > 0, container.height > 0 else { return .zero }

        let widthFromHeight = container.height * portraitCameraAspectRatio
        if widthFromHeight >= container.width {
            return CGSize(width: widthFromHeight, height: container.height)
        }

        return CGSize(
            width: container.width,
            height: container.width / portraitCameraAspectRatio
        )
    }

    private var debugDeck: some View {
        VStack(spacing: 7) {
            HStack(alignment: .top, spacing: 9) {
                telemetryHUD
                exportsButton
                recordButton
            }

            bottomHUD
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var telemetryHUD: some View {
        let debug = sessionManager.liveDebugData

        return VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 5) {
                Circle()
                    .fill(sessionManager.isRecording ? .red : .cyan)
                    .frame(width: 6, height: 6)
                    .shadow(color: sessionManager.isRecording ? .red : .cyan, radius: 5)

                Text(sessionManager.isRecording ? "REC" : "ARMED")
                    .foregroundStyle(sessionManager.isRecording ? .red : .cyan)

                Text(debug.shortTrackingState)
                    .foregroundStyle(.white)

                Text(String(format: "%04.1f FPS", debug.fps))
                    .foregroundStyle(.white.opacity(0.62))

                Spacer(minLength: 4)

                if sessionManager.isRecording {
                    Text("f \(sessionManager.recordedFrameCount)  d \(sessionManager.droppedFrameCount)")
                        .foregroundColor(sessionManager.droppedFrameCount == 0 ? Color.white.opacity(0.62) : Color.orange)
                } else {
                    Text(sessionManager.statusText)
                        .foregroundStyle(.white.opacity(0.62))
                        .lineLimit(1)
                }
            }

            HStack(spacing: 10) {
                Text(String(format: "t %.3f", debug.arTimestamp))
                Text("\(debug.imageWidth)x\(debug.imageHeight)")
                Text(String(format: "fx %.0f fy %.0f", debug.fx, debug.fy))
            }
            .foregroundStyle(.white.opacity(0.78))

            Text(String(format: "cam %+0.2f  %+0.2f  %+0.2f", debug.cameraX, debug.cameraY, debug.cameraZ))
                .foregroundStyle(.white.opacity(0.78))
        }
        .font(.system(size: 10, weight: .medium, design: .monospaced))
        .lineLimit(1)
        .padding(.horizontal, 9)
        .padding(.vertical, 7)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.white.opacity(0.07), in: RoundedRectangle(cornerRadius: 7, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 7, style: .continuous)
                .stroke(.white.opacity(0.14), lineWidth: 1)
        )
    }

    private var recordButton: some View {
        Button {
            if sessionManager.isRecording {
                sessionManager.stopRecording()
            } else {
                sessionManager.startRecording(deviceID: deviceID)
            }
        } label: {
            Image(systemName: sessionManager.isRecording ? "stop.fill" : "record.circle")
                .font(.system(size: 20, weight: .semibold))
                .foregroundStyle(.white)
                .frame(width: 40, height: 40)
                .background(sessionManager.isRecording ? Color.red.opacity(0.92) : Color.white.opacity(0.12), in: Circle())
                .overlay(Circle().stroke(.white.opacity(0.32), lineWidth: 1))
                .shadow(color: sessionManager.isRecording ? .red.opacity(0.55) : .black.opacity(0.35), radius: 7)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(sessionManager.isRecording ? "Stop Recording" : "Start Recording")
    }

    private var exportsButton: some View {
        Button {
            isShowingRecordings = true
        } label: {
            Image(systemName: "tray.and.arrow.up")
                .font(.system(size: 17, weight: .semibold))
                .foregroundStyle(.white)
                .frame(width: 36, height: 36)
                .background(Color.white.opacity(0.12), in: Circle())
                .overlay(Circle().stroke(.white.opacity(0.28), lineWidth: 1))
                .shadow(color: .black.opacity(0.35), radius: 7)
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Open Recordings")
    }

    private var bottomHUD: some View {
        HStack(alignment: .bottom, spacing: 8) {
            VStack(alignment: .leading, spacing: 5) {
                TextField("Device", text: $deviceID)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .font(.system(size: 11, weight: .medium, design: .monospaced))
                    .padding(.horizontal, 8)
                    .frame(width: 92, height: 30)
                    .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 6, style: .continuous))
                    .disabled(sessionManager.isRecording)

                if !sessionManager.lastTapText.isEmpty {
                    Text(sessionManager.lastTapText)
                        .font(.system(size: 10, weight: .medium, design: .monospaced))
                        .lineLimit(1)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 5)
                        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 6, style: .continuous))
                }
            }

            Spacer(minLength: 8)

            if let result = sessionManager.lastRecording {
                Text(result.videoURL.lastPathComponent)
                    .font(.system(size: 10, weight: .medium, design: .monospaced))
                    .lineLimit(1)
                    .truncationMode(.middle)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 6)
                    .frame(maxWidth: 220)
                    .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 6, style: .continuous))
            }
        }
        .foregroundStyle(.white)
    }
}

private struct DebugReticleOverlay: View {
    let isRecording: Bool

    var body: some View {
        ZStack {
            CrosshairShape()
                .stroke(lineColor.opacity(0.65), lineWidth: 1)

            CornerMarksShape()
                .stroke(lineColor.opacity(0.45), style: StrokeStyle(lineWidth: 1, lineCap: .square, lineJoin: .miter))
        }
        .shadow(color: lineColor.opacity(0.35), radius: 3)
    }

    private var lineColor: Color {
        isRecording ? .red : .cyan
    }
}

private struct CrosshairShape: Shape {
    func path(in rect: CGRect) -> Path {
        let center = CGPoint(x: rect.midX, y: rect.midY)
        var path = Path()
        path.move(to: CGPoint(x: center.x - 16, y: center.y))
        path.addLine(to: CGPoint(x: center.x - 5, y: center.y))
        path.move(to: CGPoint(x: center.x + 5, y: center.y))
        path.addLine(to: CGPoint(x: center.x + 16, y: center.y))
        path.move(to: CGPoint(x: center.x, y: center.y - 16))
        path.addLine(to: CGPoint(x: center.x, y: center.y - 5))
        path.move(to: CGPoint(x: center.x, y: center.y + 5))
        path.addLine(to: CGPoint(x: center.x, y: center.y + 16))
        return path
    }
}

private struct CornerMarksShape: Shape {
    func path(in rect: CGRect) -> Path {
        let inset: CGFloat = 15
        let length: CGFloat = 30
        let minX = rect.minX + inset
        let maxX = rect.maxX - inset
        let minY = rect.minY + inset
        let maxY = rect.maxY - inset
        var path = Path()

        path.move(to: CGPoint(x: minX, y: minY + length))
        path.addLine(to: CGPoint(x: minX, y: minY))
        path.addLine(to: CGPoint(x: minX + length, y: minY))

        path.move(to: CGPoint(x: maxX - length, y: minY))
        path.addLine(to: CGPoint(x: maxX, y: minY))
        path.addLine(to: CGPoint(x: maxX, y: minY + length))

        path.move(to: CGPoint(x: minX, y: maxY - length))
        path.addLine(to: CGPoint(x: minX, y: maxY))
        path.addLine(to: CGPoint(x: minX + length, y: maxY))

        path.move(to: CGPoint(x: maxX - length, y: maxY))
        path.addLine(to: CGPoint(x: maxX, y: maxY))
        path.addLine(to: CGPoint(x: maxX, y: maxY - length))

        return path
    }
}

#Preview {
    ContentView()
}
