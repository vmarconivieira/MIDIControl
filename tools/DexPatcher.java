import com.android.tools.smali.dexlib2.AccessFlags;
import com.android.tools.smali.dexlib2.DexFileFactory;
import com.android.tools.smali.dexlib2.Opcode;
import com.android.tools.smali.dexlib2.Opcodes;
import com.android.tools.smali.dexlib2.builder.BuilderInstruction;
import com.android.tools.smali.dexlib2.builder.MutableMethodImplementation;
import com.android.tools.smali.dexlib2.builder.instruction.BuilderInstruction22c;
import com.android.tools.smali.dexlib2.builder.instruction.BuilderInstruction35c;
import com.android.tools.smali.dexlib2.dexbacked.DexBackedDexFile;
import com.android.tools.smali.dexlib2.iface.ClassDef;
import com.android.tools.smali.dexlib2.iface.Method;
import com.android.tools.smali.dexlib2.iface.reference.FieldReference;
import com.android.tools.smali.dexlib2.iface.reference.MethodReference;
import com.android.tools.smali.dexlib2.immutable.ImmutableClassDef;
import com.android.tools.smali.dexlib2.immutable.ImmutableDexFile;
import com.android.tools.smali.dexlib2.immutable.ImmutableMethod;
import com.android.tools.smali.dexlib2.immutable.reference.ImmutableMethodReference;
import java.io.File;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

public class DexPatcher {
    private static String methodKey(Method m) {
        StringBuilder sb = new StringBuilder();
        sb.append(m.getName()).append('(');
        for (CharSequence p : m.getParameterTypes()) {
            sb.append(p);
        }
        sb.append(')').append(m.getReturnType());
        return sb.toString();
    }

    private static Map<String, Method> indexMethods(ClassDef cls) {
        if (cls == null) {
            throw new IllegalStateException("Expected patch class not found in patch DEX");
        }
        Map<String, Method> map = new HashMap<>();
        for (Method m : cls.getMethods()) {
            map.put(methodKey(m), m);
        }
        return map;
    }

    private static Method patchMainActivityOnCreate(Method orig) {
        MutableMethodImplementation impl = new MutableMethodImplementation(orig.getImplementation());
        List<BuilderInstruction> insns = impl.getInstructions();

        int enterIdx = -1;
        int setContentIdx = -1;
        BuilderInstruction35c enterInst = null;

        for (int i = 0; i < insns.size(); i++) {
            BuilderInstruction bi = insns.get(i);
            if (bi instanceof BuilderInstruction35c) {
                BuilderInstruction35c c = (BuilderInstruction35c) bi;
                if (c.getReference() instanceof MethodReference) {
                    MethodReference mr = (MethodReference) c.getReference();
                    if ("Lcom/p61x/keyboard/MainActivity;".equals(mr.getDefiningClass())
                            && "enterImmersiveMode".equals(mr.getName())
                            && mr.getParameterTypes().isEmpty()) {
                        enterIdx = i;
                        enterInst = c;
                    } else if ("setContentView".equals(mr.getName())
                            && mr.getParameterTypes().size() == 1
                            && "Landroid/view/View;".equals(mr.getParameterTypes().get(0).toString())) {
                        setContentIdx = i;
                    }
                }
            }
        }

        if (enterIdx < 0 || setContentIdx < 0 || enterIdx >= setContentIdx) {
            throw new IllegalStateException("Unexpected onCreate layout: enterIdx=" + enterIdx + ", setContentIdx=" + setContentIdx);
        }

        BuilderInstruction35c movedEnter = new BuilderInstruction35c(
                enterInst.getOpcode(),
                enterInst.getRegisterCount(),
                enterInst.getRegisterC(),
                enterInst.getRegisterD(),
                enterInst.getRegisterE(),
                enterInst.getRegisterF(),
                enterInst.getRegisterG(),
                enterInst.getReference()
        );

        impl.removeInstruction(enterIdx);
        int newSetContentIdx = setContentIdx - 1;
        BuilderInstruction check = impl.getInstructions().get(newSetContentIdx);
        if (!(check instanceof BuilderInstruction35c)
                || !(((BuilderInstruction35c) check).getReference() instanceof MethodReference)
                || !"setContentView".equals(((MethodReference) ((BuilderInstruction35c) check).getReference()).getName())) {
            throw new IllegalStateException("setContentView verification failed at index " + newSetContentIdx);
        }
        impl.addInstruction(newSetContentIdx + 1, movedEnter);

        System.out.println("[OK] Moved MainActivity.enterImmersiveMode() from instr #" + enterIdx + " to after setContentView (#" + (newSetContentIdx + 1) + ")");

        return new ImmutableMethod(
                orig.getDefiningClass(),
                orig.getName(),
                orig.getParameters(),
                orig.getReturnType(),
                orig.getAccessFlags(),
                orig.getAnnotations(),
                orig.getHiddenApiRestrictions(),
                impl
        );
    }

    private static Method patchMainActivityWebViewOnPageFinished(Method orig) {
        MutableMethodImplementation impl = new MutableMethodImplementation(orig.getImplementation());
        List<BuilderInstruction> insns = impl.getInstructions();
        if (insns.size() < 2) {
            throw new IllegalStateException("Unexpected MainActivity$1.onPageFinished size: " + insns.size());
        }

        BuilderInstruction first = insns.get(0);
        if (!(first instanceof BuilderInstruction22c) || first.getOpcode() != Opcode.IGET_OBJECT) {
            throw new IllegalStateException("Expected IGET_OBJECT at instr #0 of MainActivity$1.onPageFinished");
        }
        BuilderInstruction22c iget = (BuilderInstruction22c) first;
        if (!(iget.getReference() instanceof FieldReference)) {
            throw new IllegalStateException("Expected FieldReference at instr #0");
        }
        FieldReference fr = (FieldReference) iget.getReference();
        if (!"this$0".equals(fr.getName()) || !"Lcom/p61x/keyboard/MainActivity;".equals(fr.getType())) {
            throw new IllegalStateException("Unexpected field at instr #0: " + fr);
        }
        int regActivity = iget.getRegisterA();

        int lastIdx = insns.size() - 1;
        if (insns.get(lastIdx).getOpcode() != Opcode.RETURN_VOID) {
            throw new IllegalStateException("Expected RETURN_VOID at end of MainActivity$1.onPageFinished");
        }

        BuilderInstruction35c notifyPatch = new BuilderInstruction35c(
                Opcode.INVOKE_STATIC,
                1,
                regActivity, 0, 0, 0, 0,
                new ImmutableMethodReference(
                        "Lcom/p61x/keyboard/P61xPatch;",
                        "onPageFinished",
                        Collections.singletonList("Lcom/p61x/keyboard/MainActivity;"),
                        "V"
                )
        );
        impl.addInstruction(lastIdx, notifyPatch);
        System.out.println("[OK] Hooked MainActivity$1.onPageFinished -> P61xPatch.onPageFinished(v" + regActivity + ")");

        return new ImmutableMethod(
                orig.getDefiningClass(),
                orig.getName(),
                orig.getParameters(),
                orig.getReturnType(),
                orig.getAccessFlags(),
                orig.getAnnotations(),
                orig.getHiddenApiRestrictions(),
                impl
        );
    }

    private static Method replaceBodyKeepingSignature(Method orig, Method replacement) {
        if (replacement == null) {
            throw new IllegalStateException("Missing replacement method for " + orig.getDefiningClass() + "." + methodKey(orig));
        }
        return new ImmutableMethod(
                orig.getDefiningClass(),
                orig.getName(),
                orig.getParameters(),
                orig.getReturnType(),
                orig.getAccessFlags(),
                orig.getAnnotations(),
                orig.getHiddenApiRestrictions(),
                replacement.getImplementation()
        );
    }

    private static boolean isAddedHelperClass(String type) {
        return type.startsWith("Lcom/p61x/keyboard/P61xPatch")
                || type.startsWith("Lcom/p61x/keyboard/P61xUpdater")
                || type.equals("Lcom/p61x/keyboard/UpdateInstallReceiver;")
                || type.startsWith("Lcom/p61x/keyboard/UsbMidiEnhanced");
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 3) {
            System.err.println("Usage: DexPatcher <orig.dex> <patch.dex> <out.dex>");
            System.exit(1);
        }
        File origFile = new File(args[0]);
        File patchFile = new File(args[1]);
        String outPath = args[2];

        Opcodes opcodes = Opcodes.forApi(27);
        DexBackedDexFile origDex = DexFileFactory.loadDexFile(origFile, opcodes);
        DexBackedDexFile patchDex = DexFileFactory.loadDexFile(patchFile, opcodes);

        Map<String, ClassDef> patchClasses = new HashMap<>();
        List<ClassDef> classesToAdd = new ArrayList<>();
        for (ClassDef cls : patchDex.getClasses()) {
            patchClasses.put(cls.getType(), cls);
            if (isAddedHelperClass(cls.getType())) {
                classesToAdd.add(cls);
                System.out.println("[OK] Adding helper class: " + cls.getType());
            }
        }

        Map<String, Method> patchMainMethods = indexMethods(patchClasses.get("Lcom/p61x/keyboard/MainActivity;"));
        Map<String, Method> patchBridgeMethods = indexMethods(patchClasses.get("Lcom/p61x/keyboard/MainActivity$MobileBridge;"));
        Map<String, Method> patchEngineMethods = indexMethods(patchClasses.get("Lcom/p61x/keyboard/P61xEngine;"));
        Map<String, Method> patchMidiMethods = indexMethods(patchClasses.get("Lcom/p61x/keyboard/UsbMidiController;"));

        List<String> newBridgeKeys = Arrays.asList(
                "getAppVersion()Ljava/lang/String;",
                "checkGithubUpdate()V",
                "downloadAndInstallUpdate(Ljava/lang/String;)V",
                "openExternalUrl(Ljava/lang/String;)V",
                "rescanMidiDevices()Ljava/lang/String;"
        );

        Set<String> midiReplacedKeys = new HashSet<>(Arrays.asList(
                "start()V",
                "stop()V",
                "getActivePortName()Ljava/lang/String;",
                "listInputPortsJson()Lorg/json/JSONArray;",
                "selectInputPort(Ljava/lang/String;)V"
        ));

        List<ClassDef> outClasses = new ArrayList<>();
        boolean patchedMain = false;
        boolean patchedMain1 = false;
        boolean patchedBridge = false;
        boolean patchedEngine = false;
        boolean patchedMidi = false;

        for (ClassDef cls : origDex.getClasses()) {
            String type = cls.getType();
            if ("Lcom/p61x/keyboard/MainActivity;".equals(type)) {
                List<Method> newDirect = new ArrayList<>();
                boolean replacedEnter = false;
                boolean replacedLambda0 = false;
                for (Method m : cls.getDirectMethods()) {
                    String k = methodKey(m);
                    if ("enterImmersiveMode()V".equals(k)) {
                        newDirect.add(replaceBodyKeepingSignature(m, patchMainMethods.get(k)));
                        replacedEnter = true;
                        System.out.println("[OK] Replaced MainActivity.enterImmersiveMode()V");
                    } else if ("lambda$onCreate$0()V".equals(k)) {
                        newDirect.add(replaceBodyKeepingSignature(m, patchMainMethods.get(k)));
                        replacedLambda0 = true;
                        System.out.println("[OK] Replaced MainActivity.lambda$onCreate$0()V");
                    } else {
                        newDirect.add(m);
                    }
                }
                if (!replacedEnter || !replacedLambda0) {
                    throw new IllegalStateException("Missing MainActivity direct methods");
                }

                List<Method> newVirtual = new ArrayList<>();
                boolean patchedOnCreate = false;
                boolean replacedOnResume = false;
                boolean replacedOnDestroy = false;
                for (Method m : cls.getVirtualMethods()) {
                    String k = methodKey(m);
                    if ("onCreate(Landroid/os/Bundle;)V".equals(k)) {
                        newVirtual.add(patchMainActivityOnCreate(m));
                        patchedOnCreate = true;
                    } else if ("onResume()V".equals(k)) {
                        newVirtual.add(replaceBodyKeepingSignature(m, patchMainMethods.get(k)));
                        replacedOnResume = true;
                        System.out.println("[OK] Replaced MainActivity.onResume()V");
                    } else if ("onDestroy()V".equals(k)) {
                        newVirtual.add(replaceBodyKeepingSignature(m, patchMainMethods.get(k)));
                        replacedOnDestroy = true;
                        System.out.println("[OK] Replaced MainActivity.onDestroy()V");
                    } else {
                        newVirtual.add(m);
                    }
                }
                Method focusMethod = patchMainMethods.get("onWindowFocusChanged(Z)V");
                Method dispatchMethod = patchMainMethods.get("dispatchPatchEvent(Lorg/json/JSONObject;)V");
                if (focusMethod == null || dispatchMethod == null) {
                    throw new IllegalStateException("Missing added MainActivity methods in patch");
                }
                newVirtual.add(focusMethod);
                newVirtual.add(dispatchMethod);
                System.out.println("[OK] Added MainActivity.onWindowFocusChanged(Z)V and dispatchPatchEvent(JSONObject)V");

                if (!patchedOnCreate || !replacedOnResume || !replacedOnDestroy) {
                    throw new IllegalStateException("Missing MainActivity virtual methods");
                }

                outClasses.add(new ImmutableClassDef(
                        cls.getType(), cls.getAccessFlags(), cls.getSuperclass(), cls.getInterfaces(),
                        cls.getSourceFile(), cls.getAnnotations(), cls.getStaticFields(), cls.getInstanceFields(),
                        newDirect, newVirtual
                ));
                patchedMain = true;
            } else if ("Lcom/p61x/keyboard/MainActivity$1;".equals(type)) {
                List<Method> newVirtual = new ArrayList<>();
                boolean hooked = false;
                for (Method m : cls.getVirtualMethods()) {
                    if ("onPageFinished(Landroid/webkit/WebView;Ljava/lang/String;)V".equals(methodKey(m))) {
                        newVirtual.add(patchMainActivityWebViewOnPageFinished(m));
                        hooked = true;
                    } else {
                        newVirtual.add(m);
                    }
                }
                if (!hooked) {
                    throw new IllegalStateException("Missing MainActivity$1.onPageFinished");
                }
                outClasses.add(new ImmutableClassDef(
                        cls.getType(), cls.getAccessFlags(), cls.getSuperclass(), cls.getInterfaces(),
                        cls.getSourceFile(), cls.getAnnotations(), cls.getStaticFields(), cls.getInstanceFields(),
                        cls.getDirectMethods(), newVirtual
                ));
                patchedMain1 = true;
            } else if ("Lcom/p61x/keyboard/MainActivity$MobileBridge;".equals(type)) {
                List<Method> newVirtual = new ArrayList<>();
                Set<String> existing = new HashSet<>();
                for (Method m : cls.getVirtualMethods()) {
                    newVirtual.add(m);
                    existing.add(methodKey(m));
                }
                for (String key : newBridgeKeys) {
                    if (existing.contains(key)) {
                        throw new IllegalStateException("Bridge method already exists: " + key);
                    }
                    Method added = patchBridgeMethods.get(key);
                    if (added == null) {
                        throw new IllegalStateException("Missing new bridge method in patch: " + key);
                    }
                    newVirtual.add(added);
                    System.out.println("[OK] Added @JavascriptInterface MainActivity$MobileBridge." + key);
                }
                outClasses.add(new ImmutableClassDef(
                        cls.getType(), cls.getAccessFlags(), cls.getSuperclass(), cls.getInterfaces(),
                        cls.getSourceFile(), cls.getAnnotations(), cls.getStaticFields(), cls.getInstanceFields(),
                        cls.getDirectMethods(), newVirtual
                ));
                patchedBridge = true;
            } else if ("Lcom/p61x/keyboard/P61xEngine;".equals(type)) {
                List<Method> newDirect = new ArrayList<>();
                boolean wrappedPads = false;
                for (Method m : cls.getDirectMethods()) {
                    String k = methodKey(m);
                    if ("loadAllContinuousPads()V".equals(k)) {
                        newDirect.add(new ImmutableMethod(
                                m.getDefiningClass(), "loadAllContinuousPads$orig", m.getParameters(),
                                m.getReturnType(), AccessFlags.PRIVATE.getValue(), m.getAnnotations(),
                                m.getHiddenApiRestrictions(), m.getImplementation()
                        ));
                        newDirect.add(replaceBodyKeepingSignature(m, patchEngineMethods.get(k)));
                        wrappedPads = true;
                        System.out.println("[OK] Wrapped P61xEngine.loadAllContinuousPads()V with Throwable guard");
                    } else {
                        newDirect.add(m);
                    }
                }
                if (!wrappedPads) {
                    throw new IllegalStateException("Missing P61xEngine.loadAllContinuousPads()V");
                }
                outClasses.add(new ImmutableClassDef(
                        cls.getType(), cls.getAccessFlags(), cls.getSuperclass(), cls.getInterfaces(),
                        cls.getSourceFile(), cls.getAnnotations(), cls.getStaticFields(), cls.getInstanceFields(),
                        newDirect, cls.getVirtualMethods()
                ));
                patchedEngine = true;
            } else if ("Lcom/p61x/keyboard/UsbMidiController;".equals(type)) {
                List<Method> newDirect = new ArrayList<>();
                for (Method m : cls.getDirectMethods()) {
                    newDirect.add(m);
                }
                List<Method> newVirtual = new ArrayList<>();
                int replacedCount = 0;
                for (Method m : cls.getVirtualMethods()) {
                    String k = methodKey(m);
                    if (midiReplacedKeys.contains(k)) {
                        newVirtual.add(replaceBodyKeepingSignature(m, patchMidiMethods.get(k)));
                        replacedCount++;
                        System.out.println("[OK] Upgraded UsbMidiController." + k + " -> UsbMidiEnhanced");
                    } else {
                        newVirtual.add(m);
                    }
                }
                if (replacedCount != midiReplacedKeys.size()) {
                    throw new IllegalStateException("Expected " + midiReplacedKeys.size() + " UsbMidiController methods, replaced " + replacedCount);
                }
                Method dispatchHook = patchMidiMethods.get("onEnhancedMidiBytes(Ljava/lang/String;[BII)V");
                if (dispatchHook == null) {
                    throw new IllegalStateException("Missing UsbMidiController.onEnhancedMidiBytes in patch");
                }
                newVirtual.add(dispatchHook);
                System.out.println("[OK] Added UsbMidiController.onEnhancedMidiBytes(String,byte[],int,int)V");

                outClasses.add(new ImmutableClassDef(
                        cls.getType(), cls.getAccessFlags(), cls.getSuperclass(), cls.getInterfaces(),
                        cls.getSourceFile(), cls.getAnnotations(), cls.getStaticFields(), cls.getInstanceFields(),
                        newDirect, newVirtual
                ));
                patchedMidi = true;
            } else {
                outClasses.add(cls);
            }
        }

        if (!patchedMain || !patchedMain1 || !patchedBridge || !patchedEngine || !patchedMidi) {
            throw new IllegalStateException("Failed to patch all target classes: main=" + patchedMain
                    + " main1=" + patchedMain1 + " bridge=" + patchedBridge + " engine=" + patchedEngine + " midi=" + patchedMidi);
        }
        outClasses.addAll(classesToAdd);

        ImmutableDexFile newDex = new ImmutableDexFile(opcodes, outClasses);
        DexFileFactory.writeDexFile(outPath, newDex);
        System.out.println("[DONE] Wrote patched DEX to " + outPath + " (" + outClasses.size() + " classes, orig=" + origDex.getClasses().size() + ")");
    }
}
