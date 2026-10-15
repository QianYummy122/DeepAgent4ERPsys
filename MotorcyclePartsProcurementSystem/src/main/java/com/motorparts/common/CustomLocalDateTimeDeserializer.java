package com.motorparts.common;

import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.databind.DeserializationContext;
import com.fasterxml.jackson.databind.JsonDeserializer;

import java.io.IOException;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.Arrays;
import java.util.List;

/**
 * LocalDateTime 反序列化器。
 *
 * <p>历史问题：本类原先只接受 {@code yyyy-MM-dd'T'HH:mm:ss.SSS} 一种格式，
 * 而 {@link CustomLocalDateTimeSerializer} 输出的是 {@code yyyy-MM-dd HH:mm:ss}。
 * 两者不对称，导致「把接口返回的时间原样回传」必然解析失败，
 * 使 /orders/update 等接口无法做「读取-修改-写回」。
 *
 * <p>现改为宽容解析：先把分隔符统一为空格，再依次尝试多种常见格式。
 */
public class CustomLocalDateTimeDeserializer extends JsonDeserializer<LocalDateTime> {

    /** 按「信息量从多到少」排序。 */
    private static final List<DateTimeFormatter> FORMATTERS = Arrays.asList(
            DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss.SSS"),
            DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"),
            DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm"),
            DateTimeFormatter.ofPattern("yyyy-MM-dd")
    );

    @Override
    public LocalDateTime deserialize(JsonParser p, DeserializationContext ctxt) throws IOException {
        String value = p.getValueAsString();
        if (value == null || value.trim().isEmpty()) {
            return null;
        }

        String cleaned = value.trim();

        // 1. 去掉结尾的 Z
        if (cleaned.endsWith("Z") || cleaned.endsWith("z")) {
            cleaned = cleaned.substring(0, cleaned.length() - 1);
        }

        // 2. 统一日期与时间的分隔符：'T' -> ' '
        cleaned = cleaned.replace('T', ' ').replace('t', ' ').trim();

        // 3. 去掉时区偏移（形如 +08:00 / -05:00）
        int spaceIdx = cleaned.indexOf(' ');
        if (spaceIdx > 0) {
            String afterTime = cleaned.substring(spaceIdx + 1);
            int plus = afterTime.indexOf('+');
            int minus = afterTime.indexOf('-');
            int offsetIdx = plus >= 0 ? plus : minus;
            if (offsetIdx >= 0) {
                cleaned = cleaned.substring(0, spaceIdx + 1 + offsetIdx).trim();
            }
        }

        // 4. 依次尝试各格式
        for (DateTimeFormatter formatter : FORMATTERS) {
            try {
                return LocalDateTime.parse(cleaned, formatter);
            } catch (DateTimeParseException ignored) {
                // 尝试下一种格式
            }
        }

        throw new IOException(
                "无法解析时间字符串: '" + value + "'。支持格式: "
                        + "yyyy-MM-dd'T'HH:mm:ss.SSS / yyyy-MM-dd'T'HH:mm:ss / "
                        + "yyyy-MM-dd HH:mm:ss[.SSS] / yyyy-MM-dd HH:mm / yyyy-MM-dd");
    }
}
