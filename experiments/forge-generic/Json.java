package deckdoctor.generic;
import java.util.*;
/** Serialization of the probe's maps, collections, and scalar values only. */
final class Json {
    static String write(Object value) {
        if(value==null)return "null";
        if(value instanceof Boolean || value instanceof Number)return value.toString();
        if(value instanceof Map<?,?> map) {
            List<String> pairs=new ArrayList<>();for(var e:map.entrySet())pairs.add(write(e.getKey().toString())+":"+write(e.getValue()));
            return "{"+String.join(",",pairs)+"}";
        }
        if(value instanceof Iterable<?> values) {List<String> items=new ArrayList<>();for(Object item:values)items.add(write(item));return "["+String.join(",",items)+"]";}
        StringBuilder b=new StringBuilder("\"");
        for(char c:value.toString().toCharArray())switch(c) {
            case '"':b.append("\\\"");break;
            case '\\':b.append("\\\\");break;
            case '\n':b.append("\\n");break;
            case '\r':b.append("\\r");break;
            case '\t':b.append("\\t");break;
            default:if(c<32)b.append(String.format("\\u%04x",(int)c));else b.append(c);
        }
        return b.append('"').toString();
    }
}
