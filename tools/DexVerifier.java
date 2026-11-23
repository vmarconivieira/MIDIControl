import com.android.tools.smali.dexlib2.AnnotationVisibility;
import com.android.tools.smali.dexlib2.DexFileFactory;
import com.android.tools.smali.dexlib2.Opcodes;
import com.android.tools.smali.dexlib2.dexbacked.DexBackedDexFile;
import com.android.tools.smali.dexlib2.iface.Annotation;
import com.android.tools.smali.dexlib2.iface.ClassDef;
import com.android.tools.smali.dexlib2.iface.Method;
import java.io.File;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

public class DexVerifier {
    public static void main(String[] args) throws Exception {
        Opcodes opcodes = Opcodes.forApi(27);
        DexBackedDexFile orig = DexFileFactory.loadDexFile(new File(args[0]), opcodes);
        DexBackedDexFile patched = DexFileFactory.loadDexFile(new File(args[1]), opcodes);

        Map<String, ClassDef> origMap = new HashMap<>();
        for (ClassDef c : orig.getClasses()) origMap.put(c.getType(), c);
        Map<String, ClassDef> patchedMap = new HashMap<>();
        for (ClassDef c : patched.getClasses()) patchedMap.put(c.getType(), c);

        // 1. Ensure every original class is preserved
        for (String type : origMap.keySet()) {
            if (!patchedMap.containsKey(type)) {
                throw new AssertionError("Missing original class: " + type);
            }
        }
        // 2. Ensure all required new classes are present
        for (String req : Arrays.asList(
                "Lcom/p61x/keyboard/P61xPatch;",
                "Lcom/p61x/keyboard/P61xUpdater;",
                "Lcom/p61x/keyboard/UpdateInstallReceiver;",
                "Lcom/p61x/keyboard/UsbMidiEnhanced;"
        )) {
            if (!patchedMap.containsKey(req)) {
                throw new AssertionError("Missing added class: " + req);
            }
        }
        System.out.println("[OK] All " + origMap.size() + " original classes + new helper classes present; total=" + patchedMap.size());

        // 3. Verify all 56 @JavascriptInterface runtime annotations on MainActivity$MobileBridge
        ClassDef origBridge = origMap.get("Lcom/p61x/keyboard/MainActivity$MobileBridge;");
        ClassDef patchedBridge = patchedMap.get("Lcom/p61x/keyboard/MainActivity$MobileBridge;");
        int origJs = countJsInterface(origBridge);
        int patchedJs = countJsInterface(patchedBridge);
        if (origJs != 51 || patchedJs != 56) {
            throw new AssertionError("@JavascriptInterface mismatch: orig=" + origJs + " patched=" + patchedJs + " (expected 51 -> 56)");
        }
        System.out.println("[OK] MainActivity$MobileBridge has all " + patchedJs + " RUNTIME @JavascriptInterface annotations (51 orig + 5 new)");

        // 4. Verify untouched classes match fields/methods/annotations identically
        Set<String> modified = new HashSet<>(Arrays.asList(
                "Lcom/p61x/keyboard/MainActivity;",
                "Lcom/p61x/keyboard/MainActivity$1;",
                "Lcom/p61x/keyboard/MainActivity$MobileBridge;",
                "Lcom/p61x/keyboard/P61xEngine;",
                "Lcom/p61x/keyboard/UsbMidiController;"
        ));
        int untouchedChecked = 0;
        for (Map.Entry<String, ClassDef> e : origMap.entrySet()) {
            String t = e.getKey();
            if (modified.contains(t)) continue;
            ClassDef oc = e.getValue();
            ClassDef pc = patchedMap.get(t);
            if (oc.getAnnotations().size() != pc.getAnnotations().size()
                    || countAll(oc.getFields()) != countAll(pc.getFields())
                    || countAll(oc.getMethods()) != countAll(pc.getMethods())) {
                throw new AssertionError("Mismatch in untouched class " + t);
            }
            untouchedChecked++;
        }
        System.out.println("[OK] Verified " + untouchedChecked + " untouched classes match fields/methods/annotations exactly");

        // 5. Verify exact method deltas on patched classes
        assertDelta(origMap, patchedMap, "Lcom/p61x/keyboard/MainActivity;", 2);
        assertDelta(origMap, patchedMap, "Lcom/p61x/keyboard/MainActivity$1;", 0);
        assertDelta(origMap, patchedMap, "Lcom/p61x/keyboard/MainActivity$MobileBridge;", 5);
        assertDelta(origMap, patchedMap, "Lcom/p61x/keyboard/P61xEngine;", 1);
        assertDelta(origMap, patchedMap, "Lcom/p61x/keyboard/UsbMidiController;", 1);
        System.out.println("[OK] Exact expected method count deltas across all 5 patched classes");
    }

    private static void assertDelta(Map<String, ClassDef> orig, Map<String, ClassDef> patched, String cls, int expectedDelta) {
        int o = countAll(orig.get(cls).getMethods());
        int p = countAll(patched.get(cls).getMethods());
        if (p != o + expectedDelta) {
            throw new AssertionError("Method delta mismatch for " + cls + ": orig=" + o + " patched=" + p + " expectedDelta=" + expectedDelta);
        }
    }

    private static int countJsInterface(ClassDef cls) {
        int count = 0;
        for (Method m : cls.getVirtualMethods()) {
            for (Annotation a : m.getAnnotations()) {
                if ("Landroid/webkit/JavascriptInterface;".equals(a.getType())
                        && a.getVisibility() == AnnotationVisibility.RUNTIME) {
                    count++;
                }
            }
        }
        return count;
    }

    private static int countAll(Iterable<?> it) {
        int n = 0;
        for (Object ignored : it) n++;
        return n;
    }
}
