package com.knowledge.blog.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.knowledge.blog.dto.RagQueryDto;
import com.knowledge.blog.mapper.CategoryMapper;
import com.knowledge.blog.mapper.PostMapper;
import com.knowledge.blog.model.Category;
import com.knowledge.blog.model.Post;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.Authentication;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.web.util.HtmlUtils;
import org.springframework.web.reactive.function.client.WebClientRequestException;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.util.retry.Retry;

import java.time.Duration;
import java.util.Map;
import java.util.List;

@Slf4j
@Service
@RequiredArgsConstructor
public class RagService {

    private final WebClient.Builder webClientBuilder;
    private final CategoryMapper categoryMapper;
    private final PostMapper postMapper;
    private final ObjectMapper objectMapper;

    @Value("${rag.fastapi-url}")
    private String fastApiUrl;

    public RagQueryDto.Response searchAndAnswer(
            RagQueryDto.Request request,
            Authentication authentication) {
        request.setAccessScope(accessScope(authentication));
        try {
            return webClientBuilder.baseUrl(fastApiUrl).build()
                    .post()
                    .uri("/api/rag/query")
                    .bodyValue(request)
                    .retrieve()
                    .bodyToMono(RagQueryDto.Response.class)
                    .retryWhen(ragConnectionRetry())
                    .block();
        } catch (Exception e) {
            log.error("FastAPI RAG query error: {}", e.getMessage());
            RagQueryDto.Response fallback = new RagQueryDto.Response();
            fallback.setQuery(request.getQuery());
            fallback.setAnswer("AI 지식 검색 서비스 연결 중 오류가 발생했습니다: " + e.getMessage());
            fallback.setResponseTimeMs(0);
            return fallback;
        }
    }

    public RagQueryDto.LearningDirectionResponse recommendLearningDirections(
            Long postId,
            RagQueryDto.LearningDirectionRequest request,
            Authentication authentication) {
        Post post = postMapper.findById(postId);
        if (post == null) {
            return null;
        }
        RagQueryDto.AccessScope scope = accessScope(authentication);
        boolean owner = scope.getUserId() != null && scope.getUserId().equals(post.getAuthorId());
        if (!Boolean.TRUE.equals(post.getIsPublished()) && !scope.isAdmin() && !owner) {
            throw new AccessDeniedException("이 게시물의 학습 방향을 조회할 권한이 없습니다.");
        }

        RagQueryDto.LearningDirectionEngineRequest engineRequest =
                new RagQueryDto.LearningDirectionEngineRequest();
        engineRequest.setPostId(post.getId());
        engineRequest.setTitle(post.getTitle());
        engineRequest.setContent(toSearchableText(post.getContent()));
        engineRequest.setCategory(post.getCategorySection());
        engineRequest.setExistingDirections(parseDirections(post.getLearningDirections()));
        engineRequest.setCheckedDirectionIds(
                request.getCheckedDirectionIds() == null ? List.of() : request.getCheckedDirectionIds());
        // Do not derive an external search query from a private post without a
        // separate explicit-consent flow.
        engineRequest.setIncludeWeb(
                Boolean.TRUE.equals(post.getIsPublished())
                        && !Boolean.FALSE.equals(request.getIncludeWeb()));
        engineRequest.setMaxRecommendations(
                request.getMaxRecommendations() == null ? 4 : request.getMaxRecommendations());
        engineRequest.setAccessScope(scope);

        return webClientBuilder.baseUrl(fastApiUrl).build()
                .post()
                .uri("/api/rag/learning-directions")
                .bodyValue(engineRequest)
                .retrieve()
                .bodyToMono(RagQueryDto.LearningDirectionResponse.class)
                .retryWhen(ragConnectionRetry())
                .block();
    }

    public Map<String, Object> latestEvaluation() {
        return webClientBuilder.baseUrl(fastApiUrl).build()
                .get()
                .uri("/api/rag/evaluation/latest")
                .retrieve()
                .bodyToMono(new org.springframework.core.ParameterizedTypeReference<Map<String, Object>>() {})
                .retryWhen(ragConnectionRetry())
                .block();
    }

    public RagQueryDto.ClassifyResponse classifyPost(RagQueryDto.ClassifyRequest request) {
        RagQueryDto.ClassifyEngineRequest engineRequest = new RagQueryDto.ClassifyEngineRequest();
        engineRequest.setTitle(request.getTitle());
        engineRequest.setContent(request.getContent());
        engineRequest.setCategories(categoryMapper.findAll().stream().map(this::toCandidate).toList());

        return webClientBuilder.baseUrl(fastApiUrl).build()
                .post()
                .uri("/api/rag/classify")
                .bodyValue(engineRequest)
                .retrieve()
                .bodyToMono(RagQueryDto.ClassifyResponse.class)
                .retryWhen(ragConnectionRetry())
                .block();
    }

    public RagQueryDto.DraftResponse generatePostDraft(RagQueryDto.DraftRequest request) {
        RagQueryDto.DraftEngineRequest engineRequest = new RagQueryDto.DraftEngineRequest();
        engineRequest.setContent(request.getContent());
        engineRequest.setTitle(request.getTitle());
        engineRequest.setCategories(categoryMapper.findAll().stream().map(this::toCandidate).toList());

        return webClientBuilder.baseUrl(fastApiUrl).build()
                .post()
                .uri("/api/rag/draft")
                .bodyValue(engineRequest)
                .retrieve()
                .bodyToMono(RagQueryDto.DraftResponse.class)
                .retryWhen(ragConnectionRetry())
                .block();
    }

    private Retry ragConnectionRetry() {
        return Retry.backoff(8, Duration.ofSeconds(1))
                .maxBackoff(Duration.ofSeconds(5))
                .filter(WebClientRequestException.class::isInstance)
                .doBeforeRetry(signal -> log.warn(
                        "RAG connection unavailable; retrying ({}/8): {}",
                        signal.totalRetries() + 1,
                        signal.failure().getMessage()
                ));
    }

    private RagQueryDto.CategoryCandidate toCandidate(Category category) {
        RagQueryDto.CategoryCandidate candidate = new RagQueryDto.CategoryCandidate();
        candidate.setId(category.getId());
        candidate.setName(category.getName());
        candidate.setSection(category.getSection());
        candidate.setDescription(category.getDescription());
        return candidate;
    }

    private RagQueryDto.AccessScope accessScope(Authentication authentication) {
        RagQueryDto.AccessScope scope = new RagQueryDto.AccessScope();
        if (authentication == null || !authentication.isAuthenticated()) {
            return scope;
        }
        scope.setRoles(authentication.getAuthorities().stream()
                .map(authority -> authority.getAuthority())
                .toList());
        scope.setAdmin(scope.getRoles().contains("ROLE_ADMIN"));
        if (authentication instanceof JwtAuthenticationToken jwtAuthentication) {
            Number userId = jwtAuthentication.getToken().getClaim("userId");
            if (userId != null) {
                scope.setUserId(userId.longValue());
            }
            List<Number> organizationIds = jwtAuthentication.getToken().getClaim("organizationIds");
            if (organizationIds != null) {
                scope.setOrganizationIds(organizationIds.stream().map(Number::longValue).toList());
            }
        }
        return scope;
    }

    private List<String> parseDirections(String value) {
        if (value == null || value.isBlank()) return List.of();
        try {
            return objectMapper.readValue(value, new TypeReference<List<String>>() {});
        } catch (Exception ignored) {
            return value.lines().map(String::trim).filter(item -> !item.isBlank()).toList();
        }
    }

    private String toSearchableText(String content) {
        if (content == null) return "";
        return HtmlUtils.htmlUnescape(content.replaceAll("<[^>]+>", " "))
                .replaceAll("\\s+", " ")
                .trim();
    }
}
